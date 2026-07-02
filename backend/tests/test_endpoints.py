"""P8 回归测试：embeddings 与 image generation 端点 + 计费"""
import asyncio

import pytest
from sqlalchemy import select

from tests.conftest import TestSessionLocal


class _Fake:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


async def _drain():
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_embeddings(admin_client, client, monkeypatch):
    from app.services import router as core
    captured = {}

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return _Fake({
            "object": "list", "model": "openai/text-embedding-3-small",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
            "usage": {"prompt_tokens": 1000, "total_tokens": 1000},
        })

    monkeypatch.setattr(core.litellm, "aembedding", fake_aembedding)
    key = (await admin_client.post("/admin/keys", json={"name": "e"})).json()["key"]
    r = await client.post("/v1/embeddings", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "text-embedding-3-small", "input": "hello world"})
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "text-embedding-3-small"       # 回显公开名
    assert body["data"][0]["embedding"] == [0.1, 0.2, 0.3]
    assert captured["model"] == "openai/text-embedding-3-small"  # 上游用 litellm 全名

    await _drain()
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.input_tokens == 1000
        assert rec.cost_usd == pytest.approx(1000 / 1e6 * 0.02)  # 0.00002


@pytest.mark.asyncio
async def test_image_generation_billed_per_image(admin_client, client, monkeypatch):
    from app.services import router as core

    async def fake_aimage(**kwargs):
        n = kwargs.get("n", 1)
        return _Fake({"created": 1, "data": [{"url": f"http://img/{i}"} for i in range(n)]})

    monkeypatch.setattr(core.litellm, "aimage_generation", fake_aimage)
    key = (await admin_client.post("/admin/keys", json={"name": "i"})).json()["key"]
    r = await client.post("/v1/images/generations", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "dall-e-3", "prompt": "a cat", "n": 2})
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2

    await _drain()
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.cost_usd == pytest.approx(0.04 * 2)  # 每张 $0.04 × 2


@pytest.mark.asyncio
async def test_catalog_exposes_mode(admin_client, client):
    key_user = (await client.post("/auth/register", json={"email": "m8@e.com", "password": "password123", "name": "M"})).json()["access_token"]
    r = await client.get("/catalog/models", headers={"Authorization": f"Bearer {key_user}"})
    models = {m["id"]: m for m in r.json()["data"]}
    assert models["text-embedding-3-small"]["mode"] == "embedding"
    assert models["dall-e-3"]["mode"] == "image"
    assert models["dall-e-3"]["image_price"] == 0.04
    assert models["gemini-2.0-flash"]["mode"] == "chat"


@pytest.mark.asyncio
async def test_embeddings_unknown_model_404(admin_client, client):
    key = (await admin_client.post("/admin/keys", json={"name": "e"})).json()["key"]
    r = await client.post("/v1/embeddings", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "no-such", "input": "x"})
    assert r.status_code == 404
