"""P0 回归测试：新表可用、seed 幂等、默认组织回填、旧行为不受影响"""
import pytest
from sqlalchemy import select

from tests.conftest import TestSessionLocal
from app.models import (
    Organization, User, Membership,
    Provider, ModelCatalog, ApiKey,
)
from scripts.seed import seed_providers, seed_catalog, seed_default_org


async def test_new_tables_crud_smoke():
    """新表能建能写能查（多租户 + 供应商 + 目录）"""
    async with TestSessionLocal() as db:
        org = Organization(name="Acme", slug="acme")
        user = User(email="a@b.c", password_hash="x", name="A")
        db.add_all([org, user])
        await db.flush()
        db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
        provider = Provider(name="openai", litellm_prefix="openai", credential_env="OPENAI_API_KEY")
        db.add(provider)
        await db.flush()
        db.add(ModelCatalog(
            model_id="gpt-4o", provider_id=provider.id, litellm_model="openai/gpt-4o",
            input_price_per_1m=2.5, output_price_per_1m=10.0, verified=True,
        ))
        await db.commit()

    async with TestSessionLocal() as db:
        m = (await db.execute(select(ModelCatalog).where(ModelCatalog.model_id == "gpt-4o"))).scalar_one()
        assert m.input_price_per_1m == 2.5
        mem = (await db.execute(select(Membership))).scalar_one()
        assert mem.role == "owner"


async def test_seed_idempotent():
    """seed 两次结果一致：目录不重复、组织不重复"""
    async with TestSessionLocal() as db:
        ids1 = await seed_providers(db)
        added1, total1 = await seed_catalog(db, ids1)
        await seed_default_org(db)
    async with TestSessionLocal() as db:
        ids2 = await seed_providers(db)
        added2, total2 = await seed_catalog(db, ids2)
        await seed_default_org(db)

    assert ids1 == ids2
    assert added1 > 100          # litellm 价格表灌入了大量模型
    assert added2 == 0           # 第二次不再新增
    assert total1 == total2

    async with TestSessionLocal() as db:
        orgs = (await db.execute(select(Organization).where(Organization.slug == "default"))).scalars().all()
        assert len(orgs) == 1
        # 现有 10 个模型名必须仍在目录中（行为不变保证）
        for legacy in ("gemini-2.5-flash", "deepseek-v3-250324", "deepseek-r1-250528"):
            row = (await db.execute(select(ModelCatalog).where(ModelCatalog.model_id == legacy))).scalar_one_or_none()
            assert row is not None, f"legacy model missing: {legacy}"


async def test_default_org_backfills_existing_keys(admin_client):
    """先建 Key（org_id 为空），seed 后应回填到默认组织"""
    resp = await admin_client.post("/admin/keys", json={"name": "pre-seed-key"})
    assert resp.status_code == 201

    async with TestSessionLocal() as db:
        ids = await seed_providers(db)
        await seed_catalog(db, ids)
        await seed_default_org(db)

    async with TestSessionLocal() as db:
        key = (await db.execute(select(ApiKey))).scalar_one()
        org = (await db.execute(select(Organization).where(Organization.slug == "default"))).scalar_one()
        assert key.org_id == org.id
