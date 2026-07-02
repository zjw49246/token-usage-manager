"""P24 回归测试：Discord + 通用 OIDC 登录"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.config import settings


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_discord_enabled_and_url(monkeypatch):
    monkeypatch.setattr(settings, "oauth_discord_client_id", "dc_id")
    monkeypatch.setattr(settings, "oauth_discord_client_secret", "dc_secret")
    async with await _client() as c:
        assert "discord" in (await c.get("/auth/oauth/providers")).json()["providers"]
        r = await c.get("/auth/oauth/discord/url", params={"redirect_uri": "http://app/cb"})
        assert r.status_code == 200
        assert r.json()["authorize_url"].startswith("https://discord.com/api/oauth2/authorize?")
        assert "client_id=dc_id" in r.json()["authorize_url"]


@pytest.mark.asyncio
async def test_oidc_discovery_and_url(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "https://idp.example.com")
    monkeypatch.setattr(settings, "oidc_client_id", "oidc_id")
    monkeypatch.setattr(settings, "oidc_client_secret", "oidc_secret")
    from app.services import oauth
    # 预置发现结果，跳过真实 HTTP
    monkeypatch.setattr(oauth, "_oidc_cache", {
        "authorize_url": "https://idp.example.com/authorize",
        "token_url": "https://idp.example.com/token",
        "userinfo_url": "https://idp.example.com/userinfo",
        "scope": "openid email profile",
    })
    async with await _client() as c:
        assert "oidc" in (await c.get("/auth/oauth/providers")).json()["providers"]
        r = await c.get("/auth/oauth/oidc/url", params={"redirect_uri": "http://app/cb"})
        assert r.status_code == 200
        assert r.json()["authorize_url"].startswith("https://idp.example.com/authorize?")


@pytest.mark.asyncio
async def test_discord_exchange_creates_user(monkeypatch):
    monkeypatch.setattr(settings, "oauth_discord_client_id", "dc_id")
    monkeypatch.setattr(settings, "oauth_discord_client_secret", "dc_secret")
    from app.services import oauth

    async def fake_exchange(provider, code, redirect_uri):
        assert provider == "discord"
        return {"email": "dc@example.com", "name": "DiscordUser"}
    monkeypatch.setattr(oauth, "exchange", fake_exchange)

    async with await _client() as c:
        r = await c.post("/auth/oauth/discord/exchange", json={"code": "x", "redirect_uri": "http://app/cb"})
        assert r.status_code == 200
        me = await c.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
        assert me.json()["email"] == "dc@example.com"
