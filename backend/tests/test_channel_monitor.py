"""P28 回归测试：通道成功率计数 + 巡检"""
import asyncio

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from tests.conftest import TestSessionLocal
from app.models import Provider, Channel


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion():
    return {"id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


async def _make_channel(api_key="k", model="gemini-2.0-flash", priority=0, name="c"):
    async with TestSessionLocal() as db:
        prov = (await db.execute(select(Provider).where(Provider.name == "google"))).scalar_one()
        ch = Channel(name=name, provider_id=prov.id, api_key=api_key, models=[model], enabled=True, priority=priority)
        db.add(ch)
        await db.commit()
        return ch.id


async def _superadmin(c, email="sa@e.com"):
    tok = (await c.post("/auth/register", json={"email": email, "password": "password123", "name": "SA"})).json()["access_token"]
    await c.post("/admin/superadmin", headers={"Authorization": "Bearer test-admin-token"}, json={"email": email})
    return tok


@pytest.mark.asyncio
async def test_success_rate_counters(admin_client, client, monkeypatch):
    from app.services import router as core
    good = await _make_channel(api_key="keyB", priority=5, name="good")
    bad = await _make_channel(api_key="keyA", priority=10, name="bad")

    async def fake_acompletion(**kwargs):
        if kwargs.get("api_key") == "keyA":
            raise RuntimeError("down")
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    for _ in range(2):
        await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
    await asyncio.sleep(0.1)

    async with TestSessionLocal() as db:
        b = await db.get(Channel, bad)
        g = await db.get(Channel, good)
        assert b.error_count == 2 and b.success_count == 0   # bad 每次先失败
        assert g.success_count == 2                          # good 每次转成功


@pytest.mark.asyncio
async def test_test_all_endpoint(monkeypatch):
    from app.services import router as core
    await _make_channel(api_key="k1", name="c1")
    await _make_channel(api_key="k2", name="c2")

    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        tok = await _superadmin(c)
        r = await c.post("/channels/test-all", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == 2 and all(x["ok"] for x in results)

        # 通道列表带 success_rate 字段
        lst = await c.get("/channels", headers={"Authorization": f"Bearer {tok}"})
        assert "success_rate" in lst.json()[0]
