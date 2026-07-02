"""第三方登录（P11/P24）：GitHub / Google / Discord + 通用 OIDC。未配的 provider 不启用。"""
import secrets
from urllib.parse import urlencode

import httpx

from app.config import settings

# 静态 provider 端点
_STATIC = {
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "emails_url": "https://api.github.com/user/emails",
        "scope": "read:user user:email",
    },
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope": "openid email profile",
    },
    "discord": {
        "authorize_url": "https://discord.com/api/oauth2/authorize",
        "token_url": "https://discord.com/api/oauth2/token",
        "userinfo_url": "https://discord.com/api/users/@me",
        "scope": "identify email",
    },
}

_CREDS = {
    "github": lambda: (settings.oauth_github_client_id, settings.oauth_github_client_secret),
    "google": lambda: (settings.oauth_google_client_id, settings.oauth_google_client_secret),
    "discord": lambda: (settings.oauth_discord_client_id, settings.oauth_discord_client_secret),
    "oidc": lambda: (settings.oidc_client_id, settings.oidc_client_secret),
}

_oidc_cache: dict | None = None


def _creds(provider: str) -> tuple[str, str]:
    return _CREDS.get(provider, lambda: ("", ""))()


def enabled(provider: str) -> bool:
    if provider == "oidc":
        return bool(settings.oidc_issuer and settings.oidc_client_id)
    return provider in _STATIC and bool(_creds(provider)[0])


def enabled_providers() -> list[str]:
    return [p for p in list(_STATIC) + ["oidc"] if enabled(p)]


def new_state() -> str:
    return secrets.token_urlsafe(24)


async def _get_cfg(provider: str) -> dict:
    global _oidc_cache
    if provider in _STATIC:
        return _STATIC[provider]
    if provider == "oidc":
        if _oidc_cache is None:
            issuer = settings.oidc_issuer.rstrip("/")
            async with httpx.AsyncClient(timeout=15) as client:
                disc = (await client.get(f"{issuer}/.well-known/openid-configuration")).json()
            _oidc_cache = {
                "authorize_url": disc["authorization_endpoint"],
                "token_url": disc["token_endpoint"],
                "userinfo_url": disc["userinfo_endpoint"],
                "scope": "openid email profile",
            }
        return _oidc_cache
    raise ValueError(f"Unknown provider {provider}")


async def build_authorize_url(provider: str, redirect_uri: str, state: str) -> str:
    cfg = await _get_cfg(provider)
    client_id, _ = _creds(provider)
    params = {
        "client_id": client_id, "redirect_uri": redirect_uri,
        "scope": cfg["scope"], "state": state, "response_type": "code",
    }
    return f"{cfg['authorize_url']}?{urlencode(params)}"


async def exchange(provider: str, code: str, redirect_uri: str) -> dict:
    """用 code 换 token 并取用户信息，返回 {email, name}。"""
    cfg = await _get_cfg(provider)
    client_id, client_secret = _creds(provider)
    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post(
            cfg["token_url"],
            data={
                "client_id": client_id, "client_secret": client_secret,
                "code": code, "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise ValueError("No access_token from provider")

        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        info = (await client.get(cfg["userinfo_url"], headers=headers)).json()

        email = info.get("email")
        name = info.get("name") or info.get("login") or info.get("username") or (email or "").split("@")[0]

        if not email and provider == "github":
            emails = (await client.get(cfg["emails_url"], headers=headers)).json()
            primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
            email = (primary or (emails[0] if emails else {})).get("email")

    if not email:
        raise ValueError("Could not obtain email from provider")
    return {"email": email, "name": name}
