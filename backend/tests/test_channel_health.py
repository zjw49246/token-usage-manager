"""P18 回归测试：通道健康——测试端点 + 故障时自动标记 status/禁用"""
import asyncio

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.config import settings
from tests.conftest import TestSessionLocal
from app.models import Provider, Channel


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion():
    return {"id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


async def _make_channel(api_key="k", model="gemini-2.0-flash", enabled=True, priority=0, name="c"):
    async with TestSessionLocal() as db:
        prov = (await db.execute(select(Provider).where(Provider.name == "google"))).scalar_one()
        ch = Channel(name=name, provider_id=prov.id, api_key=api_key, models=[model], enabled=enabled, priority=priority)
        db.add(ch)
        await db.commit()
        return ch.id


async def _superadmin(c, email="sa@e.com"):
    tok = (await c.post("/auth/register", json={"email": email, "password": "password123", "name": "SA"})).json()["access_token"]
    await c.post("/admin/superadmin", headers={"Authorization": "Bearer test-admin-token"}, json={"email": email})
    return tok


@pytest.mark.asyncio
async def test_channel_test_endpoint_ok(monkeypatch):
    from app.services import router as core
    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)
    cid = await _make_channel()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        tok = await _superadmin(c)
        r = await c.post(f"/channels/{cid}/test", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
    async with TestSessionLocal() as db:
        assert (await db.get(Channel, cid)).status == "active"


@pytest.mark.asyncio
async def test_channel_test_endpoint_error(monkeypatch):
    import litellm
    async def boom(**kwargs):
        raise RuntimeError("bad key")
    monkeypatch.setattr(litellm, "acompletion", boom)
    cid = await _make_channel(api_key="bad")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        tok = await _superadmin(c)
        r = await c.post(f"/channels/{cid}/test", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        assert r.json()["ok"] is False
    async with TestSessionLocal() as db:
        assert (await db.get(Channel, cid)).status == "error"


@pytest.mark.asyncio
async def test_failover_marks_channel_error(admin_client, client, monkeypatch):
    from app.services import router as core
    bad = await _make_channel(api_key="keyA", priority=10, name="A-bad")   # 高优先先试
    good = await _make_channel(api_key="keyB", priority=5, name="B-good")

    async def fake_acompletion(**kwargs):
        if kwargs.get("api_key") == "keyA":
            raise RuntimeError("channel down")
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    r = await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200
    await asyncio.sleep(0.1)
    async with TestSessionLocal() as db:
        assert (await db.get(Channel, bad)).status == "error"    # 失败通道标记 error
        assert (await db.get(Channel, good)).status == "active"  # 成功通道标记 active


@pytest.mark.asyncio
async def test_auto_disable_on_auth_error(admin_client, client, monkeypatch):
    from app.services import router as core
    monkeypatch.setattr(settings, "channel_auto_disable", True)
    bad = await _make_channel(api_key="keyA", priority=10, name="A-bad")
    good = await _make_channel(api_key="keyB", priority=5, name="B-good")

    class AuthErr(Exception):
        status_code = 401

    async def fake_acompletion(**kwargs):
        if kwargs.get("api_key") == "keyA":
            raise AuthErr()
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                      json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
    await asyncio.sleep(0.1)
    async with TestSessionLocal() as db:
        ch = await db.get(Channel, bad)
        assert ch.status == "error" and ch.enabled is False  # 鉴权错误自动禁用
