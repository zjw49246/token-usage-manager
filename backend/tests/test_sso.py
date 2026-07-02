"""P11 回归测试：第三方登录（GitHub/Google OAuth）"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.config import settings


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_providers_reflect_config(monkeypatch):
    async with await _client() as c:
        # 未配置 → 空
        assert (await c.get("/auth/oauth/providers")).json()["providers"] == []
        # 配了 github
        monkeypatch.setattr(settings, "oauth_github_client_id", "gh_id")
        monkeypatch.setattr(settings, "oauth_github_client_secret", "gh_secret")
        assert (await c.get("/auth/oauth/providers")).json()["providers"] == ["github"]


@pytest.mark.asyncio
async def test_authorize_url(monkeypatch):
    monkeypatch.setattr(settings, "oauth_github_client_id", "gh_id")
    monkeypatch.setattr(settings, "oauth_github_client_secret", "gh_secret")
    async with await _client() as c:
        r = await c.get("/auth/oauth/github/url", params={"redirect_uri": "http://app/cb"})
        assert r.status_code == 200
        url = r.json()["authorize_url"]
        assert url.startswith("https://github.com/login/oauth/authorize?")
        assert "client_id=gh_id" in url and "redirect_uri=http" in url
        assert r.json()["state"]


@pytest.mark.asyncio
async def test_url_not_configured():
    async with await _client() as c:
        assert (await c.get("/auth/oauth/github/url", params={"redirect_uri": "http://x"})).status_code == 400


@pytest.mark.asyncio
async def test_exchange_creates_user_and_org(monkeypatch):
    monkeypatch.setattr(settings, "oauth_github_client_id", "gh_id")
    monkeypatch.setattr(settings, "oauth_github_client_secret", "gh_secret")
    from app.services import oauth

    async def fake_exchange(provider, code, redirect_uri):
        return {"email": "sso@example.com", "name": "SSO User"}
    monkeypatch.setattr(oauth, "exchange", fake_exchange)

    async with await _client() as c:
        r = await c.post("/auth/oauth/github/exchange", json={"code": "abc", "redirect_uri": "http://app/cb"})
        assert r.status_code == 200
        access = r.json()["access_token"]

        me = await c.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert me.json()["email"] == "sso@example.com"
        # 首次登录建了个人组织（owner）
        orgs = await c.get("/orgs", headers={"Authorization": f"Bearer {access}"})
        assert len(orgs.json()) == 1 and orgs.json()[0]["role"] == "owner"


@pytest.mark.asyncio
async def test_exchange_existing_email_logs_in(monkeypatch):
    monkeypatch.setattr(settings, "oauth_google_client_id", "g_id")
    monkeypatch.setattr(settings, "oauth_google_client_secret", "g_secret")
    from app.services import oauth

    async with await _client() as c:
        # 先用邮箱注册
        await c.post("/auth/register", json={"email": "dup@example.com", "password": "password123", "name": "Dup"})

        async def fake_exchange(provider, code, redirect_uri):
            return {"email": "dup@example.com", "name": "Dup"}
        monkeypatch.setattr(oauth, "exchange", fake_exchange)

        r = await c.post("/auth/oauth/google/exchange", json={"code": "abc", "redirect_uri": "http://app/cb"})
        assert r.status_code == 200
        # 不应重复建用户 → 仍是同一账号，1 个组织
        access = r.json()["access_token"]
        orgs = await c.get("/orgs", headers={"Authorization": f"Bearer {access}"})
        assert len(orgs.json()) == 1
