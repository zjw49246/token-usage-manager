"""P9 回归测试：Stripe 充值（checkout + webhook 幂等入账）"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.config import settings


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


async def _owner_org(c, email="s@e.com"):
    tok = (await c.post("/auth/register", json={"email": email, "password": "password123", "name": "S"})).json()["access_token"]
    oid = (await c.get("/orgs", headers=_auth(tok))).json()[0]["id"]
    return tok, oid


@pytest.mark.asyncio
async def test_checkout_requires_stripe_config():
    async with await _client() as c:
        tok, oid = await _owner_org(c, "nocfg@e.com")
        r = await c.post(f"/orgs/{oid}/credits/checkout", headers=_auth(tok),
                         json={"amount_usd": 20, "success_url": "http://x/ok", "cancel_url": "http://x/no"})
        assert r.status_code == 400  # 未配置 Stripe


@pytest.mark.asyncio
async def test_checkout_returns_url(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    from app.services import payments

    def fake_create(org_id, amount_usd, success_url, cancel_url):
        assert amount_usd == 20
        return f"https://checkout.stripe.com/pay/{org_id}"

    monkeypatch.setattr(payments, "create_checkout_session", fake_create)
    async with await _client() as c:
        tok, oid = await _owner_org(c, "cfg@e.com")
        r = await c.post(f"/orgs/{oid}/credits/checkout", headers=_auth(tok),
                         json={"amount_usd": 20, "success_url": "http://x/ok", "cancel_url": "http://x/no"})
        assert r.status_code == 200
        assert r.json()["checkout_url"].endswith(str(oid))


@pytest.mark.asyncio
async def test_webhook_credits_org_idempotent(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_x")
    from app.services import payments

    async with await _client() as c:
        tok, oid = await _owner_org(c, "wh@e.com")
        before = (await c.get(f"/orgs/{oid}/credits", headers=_auth(tok))).json()["balance_usd"]

        # 伪造 webhook 事件解析结果
        def fake_parse(payload, sig):
            return {"org_id": oid, "amount_usd": 50.0, "ref": "pi_123"}

        monkeypatch.setattr(payments, "parse_webhook_event", fake_parse)

        r1 = await c.post("/billing/stripe/webhook", content=b"{}", headers={"stripe-signature": "sig"})
        assert r1.status_code == 200 and r1.json()["credited"] is True
        # 重复投递同一支付 → 不重复入账
        r2 = await c.post("/billing/stripe/webhook", content=b"{}", headers={"stripe-signature": "sig"})
        assert r2.status_code == 200 and r2.json()["credited"] is False

        after = (await c.get(f"/orgs/{oid}/credits", headers=_auth(tok))).json()
        assert after["balance_usd"] == pytest.approx(before + 50.0)
        assert sum(1 for t in after["transactions"] if t["ref"] == "pi_123") == 1


@pytest.mark.asyncio
async def test_webhook_ignores_non_topup(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    from app.services import payments
    monkeypatch.setattr(payments, "parse_webhook_event", lambda p, s: None)
    async with await _client() as c:
        r = await c.post("/billing/stripe/webhook", content=b"{}", headers={"stripe-signature": "sig"})
        assert r.status_code == 200 and r.json() == {"received": True}
