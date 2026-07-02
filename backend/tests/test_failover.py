"""P6 回归测试：多通道负载均衡 + 失败故障转移 + 通道管理"""
import asyncio

import pytest
from sqlalchemy import select

from tests.conftest import TestSessionLocal
from app.models import Provider, Channel


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion(text="ok"):
    return {
        "id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }


async def _mk_channels(model_id="gemini-2.0-flash", specs=None):
    """建若干服务同一模型的通道，返回 provider id。specs: list of (name, api_key, priority, weight)"""
    async with TestSessionLocal() as db:
        prov = (await db.execute(select(Provider).where(Provider.name == "google"))).scalar_one()
        for name, key, prio, weight in (specs or []):
            db.add(Channel(name=name, provider_id=prov.id, api_key=key,
                           models=[model_id], weight=weight, priority=prio, enabled=True))
        await db.commit()
        return prov.id


@pytest.mark.asyncio
async def test_failover_first_fails_second_succeeds(admin_client, client, monkeypatch):
    """通道A失败 → 自动转到通道B成功（200）"""
    from app.services import router as core
    await _mk_channels(specs=[("A-bad", "keyA", 10, 1), ("B-good", "keyB", 5, 1)])

    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs.get("api_key"))
        if kwargs.get("api_key") == "keyA":
            raise RuntimeError("channel A down")
        return _FakeResp(_completion())

    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    r = await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200
    # A（高优先）先试且失败，再转 B
    assert calls[0] == "keyA"
    assert "keyB" in calls


@pytest.mark.asyncio
async def test_all_channels_fail_returns_error(admin_client, client, monkeypatch):
    """所有通道都失败 → 返回上游错误状态码"""
    from app.services import router as core
    await _mk_channels(specs=[("A", "keyA", 5, 1), ("B", "keyB", 5, 1)])

    class Boom(Exception):
        status_code = 503
        message = "all down"

    async def fake_acompletion(**kwargs):
        raise Boom()

    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)
    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    r = await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_max_retries_caps_attempts(admin_client, client, monkeypatch):
    """max_retries 限制最多尝试通道数（默认 2）"""
    from app.services import router as core
    from app.config import settings
    monkeypatch.setattr(settings, "max_retries", 2)
    # 4 条同优先级的坏通道，但最多只尝试 max_retries+... 实际上限 = min(len, max_retries+1)? 见 _attempts
    await _mk_channels(specs=[(f"C{i}", f"key{i}", 5, 1) for i in range(4)])

    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(1)
        raise RuntimeError("down")

    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)
    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                      json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
    # 首次 + max_retries 次故障转移 = 3 次尝试
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_no_channels_uses_legacy_route(admin_client, client, monkeypatch):
    """无通道配置时回退单路由（向后兼容），仍可成功"""
    from app.services import router as core

    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion())

    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)
    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    r = await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200


# ── 通道管理（超管）──

@pytest.mark.asyncio
async def test_channel_crud_requires_superadmin(client):
    """普通用户不能管理通道；超管可以"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 注册普通用户
        tok = (await c.post("/auth/register", json={"email": "u@e.com", "password": "password123", "name": "U"})).json()["access_token"]
        r = await c.get("/channels", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403

        # 用 admin token 提升为超管
        promo = await c.post("/admin/superadmin", headers={"Authorization": "Bearer test-admin-token"}, json={"email": "u@e.com"})
        assert promo.status_code == 200
        # 重新登录拿新身份（is_superadmin 在 DB，get_current_user 每次查库，旧 token 也生效）
        prov = (await c.get("/channels/providers", headers={"Authorization": f"Bearer {tok}"})).json()
        assert len(prov) > 0
        pid = [p for p in prov if p["name"] == "google"][0]["id"]

        created = await c.post("/channels", headers={"Authorization": f"Bearer {tok}"},
                               json={"name": "ch1", "provider_id": pid, "api_key": "sk-x", "models": ["gemini-2.0-flash"], "weight": 2, "priority": 3})
        assert created.status_code == 201
        assert created.json()["has_key"] is True  # 不回显明文，只报是否配了

        lst = await c.get("/channels", headers={"Authorization": f"Bearer {tok}"})
        assert len(lst.json()) == 1
