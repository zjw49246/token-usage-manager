"""P4 回归测试：额度赠送 / 充值 / 欠额闸门 / 消费扣减台账"""
import asyncio

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.config import settings


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


async def _register(c, email, name="U"):
    r = await c.post("/auth/register", json={"email": email, "password": "password123", "name": name})
    return r.json()["access_token"]


async def _org_id(c, token):
    return (await c.get("/orgs", headers=_auth(token))).json()[0]["id"]


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion(pt=100, ct=200):
    return {
        "id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct},
    }


@pytest.mark.asyncio
async def test_welcome_grant():
    async with await _client() as c:
        tok = await _register(c, "grant@example.com")
        oid = await _org_id(c, tok)
        credits = (await c.get(f"/orgs/{oid}/credits", headers=_auth(tok))).json()
        assert credits["balance_usd"] == settings.welcome_credit_usd
        assert any(t["type"] == "grant" for t in credits["transactions"])


@pytest.mark.asyncio
async def test_topup_owner_only():
    async with await _client() as c:
        owner = await _register(c, "o@example.com", "Owner")
        await _register(c, "mem@example.com", "Mem")
        oid = await _org_id(c, owner)
        await c.post(f"/orgs/{oid}/members", headers=_auth(owner), json={"email": "mem@example.com", "role": "member"})
        member = (await c.post("/auth/login", json={"email": "mem@example.com", "password": "password123"})).json()["access_token"]

        # owner 充值
        r = await c.post(f"/orgs/{oid}/credits", headers=_auth(owner), json={"amount_usd": 20})
        assert r.status_code == 200
        assert r.json()["balance_usd"] == settings.welcome_credit_usd + 20
        assert any(t["type"] == "topup" for t in r.json()["transactions"])

        # member 不能充值
        r2 = await c.post(f"/orgs/{oid}/credits", headers=_auth(member), json={"amount_usd": 5})
        assert r2.status_code == 403


@pytest.mark.asyncio
async def test_insufficient_credits_402(monkeypatch):
    # 关掉赠送额度，让新组织余额为 0 → 触发欠额闸门
    monkeypatch.setattr(settings, "welcome_credit_usd", 0.0)
    async with await _client() as c:
        tok = await _register(c, "broke@example.com")
        oid = await _org_id(c, tok)
        key = (await c.post(f"/orgs/{oid}/keys", headers=_auth(tok), json={"name": "k"})).json()["key"]
        r = await c.post("/v1/chat/completions", headers=_auth(key),
                         json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
        assert r.status_code == 402
        assert "credit" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_usage_debits_balance(monkeypatch):
    from app.services import router as core
    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    async with await _client() as c:
        tok = await _register(c, "spend@example.com")
        oid = await _org_id(c, tok)
        key = (await c.post(f"/orgs/{oid}/keys", headers=_auth(tok), json={"name": "k"})).json()["key"]

        r = await c.post("/v1/chat/completions", headers=_auth(key),
                         json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
        assert r.status_code == 200
        await asyncio.sleep(0.05)  # 等后台记账/扣减

        credits = (await c.get(f"/orgs/{oid}/credits", headers=_auth(tok))).json()
        cost = 100 / 1e6 * 0.1 + 200 / 1e6 * 0.4  # = 0.00009
        assert credits["balance_usd"] == pytest.approx(settings.welcome_credit_usd - cost)
        assert any(t["type"] == "usage" for t in credits["transactions"])
