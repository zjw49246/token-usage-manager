"""P10 回归测试：成员级预算（每用户在组织内的消费上限）"""
import asyncio

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion():
    return {
        "id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
    }


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.mark.asyncio
async def test_member_budget_shown_and_enforced(monkeypatch):
    from app.services import router as core

    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    async with await _client() as c:
        owner = (await c.post("/auth/register", json={"email": "o@e.com", "password": "password123", "name": "O"})).json()["access_token"]
        await c.post("/auth/register", json={"email": "adm@e.com", "password": "password123", "name": "A"})
        oid = (await c.get("/orgs", headers=_auth(owner))).json()[0]["id"]

        # 以 admin 身份加入，并设一个很小的预算（cost/次=0.00009）
        r = await c.post(f"/orgs/{oid}/members", headers=_auth(owner),
                         json={"email": "adm@e.com", "role": "admin", "budget_usd": 0.00005})
        assert r.status_code == 201
        assert r.json()["budget_usd"] == 0.00005

        # 成员列表回显预算
        members = (await c.get(f"/orgs/{oid}/members", headers=_auth(owner))).json()
        adm = [m for m in members if m["email"] == "adm@e.com"][0]
        assert adm["budget_usd"] == 0.00005

        admin = (await c.post("/auth/login", json={"email": "adm@e.com", "password": "password123"})).json()["access_token"]
        key = (await c.post(f"/orgs/{oid}/keys", headers=_auth(admin), json={"name": "k"})).json()["key"]
        h = {"Authorization": f"Bearer {key}"}
        body = {"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]}

        # 第一次：预算未用完，放行；记账后累计 0.00009 > 0.00005
        r1 = await c.post("/v1/chat/completions", headers=h, json=body)
        assert r1.status_code == 200
        await asyncio.sleep(0.05)

        # 第二次：该成员累计消费已超预算 → 429
        r2 = await c.post("/v1/chat/completions", headers=h, json=body)
        assert r2.status_code == 429
        assert "budget" in r2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_no_budget_unlimited(monkeypatch):
    from app.services import router as core

    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    async with await _client() as c:
        owner = (await c.post("/auth/register", json={"email": "o2@e.com", "password": "password123", "name": "O"})).json()["access_token"]
        oid = (await c.get("/orgs", headers=_auth(owner))).json()[0]["id"]
        key = (await c.post(f"/orgs/{oid}/keys", headers=_auth(owner), json={"name": "k"})).json()["key"]
        h = {"Authorization": f"Bearer {key}"}
        body = {"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]}
        # owner 无预算 → 多次调用都放行
        for _ in range(3):
            r = await c.post("/v1/chat/completions", headers=h, json=body)
            assert r.status_code == 200
            await asyncio.sleep(0.02)
