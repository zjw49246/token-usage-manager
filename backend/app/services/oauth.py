"""第三方登录（P11）：GitHub / Google OAuth2。未配 client_id 的 provider 不启用。"""
import secrets
from urllib.parse import urlencode

import httpx

from app.config import settings

PROVIDERS = {
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
}


def _creds(provider: str) -> tuple[str, str]:
    return {
        "github": (settings.oauth_github_client_id, settings.oauth_github_client_secret),
        "google": (settings.oauth_google_client_id, settings.oauth_google_client_secret),
    }.get(provider, ("", ""))


def enabled(provider: str) -> bool:
    return provider in PROVIDERS and bool(_creds(provider)[0])


def enabled_providers() -> list[str]:
    return [p for p in PROVIDERS if enabled(p)]


def new_state() -> str:
    return secrets.token_urlsafe(24)


def build_authorize_url(provider: str, redirect_uri: str, state: str) -> str:
    cfg = PROVIDERS[provider]
    client_id, _ = _creds(provider)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": cfg["scope"],
        "state": state,
        "response_type": "code",
    }
    return f"{cfg['authorize_url']}?{urlencode(params)}"


async def exchange(provider: str, code: str, redirect_uri: str) -> dict:
    """用 code 换 token 并取用户信息，返回 {email, name}。"""
    cfg = PROVIDERS[provider]
    client_id, client_secret = _creds(provider)
    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post(
            cfg["token_url"],
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
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
        name = info.get("name") or info.get("login") or (email or "").split("@")[0]

        # GitHub 主邮箱可能不在 /user 里，需另查 /user/emails
        if not email and provider == "github":
            emails = (await client.get(cfg["emails_url"], headers=headers)).json()
            primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
            email = (primary or (emails[0] if emails else {})).get("email")

    if not email:
        raise ValueError("Could not obtain email from provider")
    return {"email": email, "name": name}
