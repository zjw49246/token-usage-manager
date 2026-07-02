"""P23 回归测试：组织价格倍率"""
import asyncio

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from tests.conftest import TestSessionLocal


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion():
    return {"id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}}


async def _superadmin(c, email="sa@e.com"):
    tok = (await c.post("/auth/register", json={"email": email, "password": "password123", "name": "SA"})).json()["access_token"]
    await c.post("/admin/superadmin", headers={"Authorization": "Bearer test-admin-token"}, json={"email": email})
    return tok


@pytest.mark.asyncio
async def test_org_multiplier_scales_cost(monkeypatch):
    from app.services import router as core
    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        tok = await _superadmin(c)
        oid = (await c.get("/orgs", headers={"Authorization": f"Bearer {tok}"})).json()[0]["id"]
        # 设 2.0 倍价
        r = await c.post("/admin/superadmin", headers={"Authorization": "Bearer test-admin-token"}, json={"email": "sa@e.com"})
        r = await c.patch(f"/orgs/{oid}/pricing", headers={"Authorization": f"Bearer {tok}"}, json={"price_multiplier": 2.0})
        assert r.status_code == 200 and r.json()["price_multiplier"] == 2.0

        key = (await c.post(f"/orgs/{oid}/keys", headers={"Authorization": f"Bearer {tok}"}, json={"name": "k"})).json()["key"]
        await c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                     json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
        await asyncio.sleep(0.05)

        from app.models import UsageRecord
        async with TestSessionLocal() as db:
            rec = (await db.execute(select(UsageRecord).where(UsageRecord.org_id == oid))).scalar_one()
            base = 100 / 1e6 * 0.1 + 200 / 1e6 * 0.4  # 0.00009
            assert rec.cost_usd == pytest.approx(base * 2.0)  # 倍率生效


@pytest.mark.asyncio
async def test_pricing_requires_superadmin(client):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        tok = (await c.post("/auth/register", json={"email": "u@e.com", "password": "password123", "name": "U"})).json()["access_token"]
        oid = (await c.get("/orgs", headers={"Authorization": f"Bearer {tok}"})).json()[0]["id"]
        r = await c.patch(f"/orgs/{oid}/pricing", headers={"Authorization": f"Bearer {tok}"}, json={"price_multiplier": 0.5})
        assert r.status_code == 403
