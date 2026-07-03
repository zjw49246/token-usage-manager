"""用户鉴权路由（P2 多租户 + P11 SSO）：注册 / 登录 / 刷新 / 当前用户 / 第三方登录"""
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Organization, Membership
from app.schemas import RegisterIn, LoginIn, RefreshIn, TokenPair, UserOut, OAuthExchangeIn
from app.services.user_auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)
from app.services import oauth

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(name: str, suffix: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"
    return f"{base}-{suffix}"


async def provision_user(db: AsyncSession, email: str, name: str, password_hash: str) -> User:
    """建用户 + 个人组织(owner)（注册与 SSO 首次登录共用）"""
    user = User(email=email, password_hash=password_hash, name=name)
    db.add(user)
    await db.flush()
    org = Organization(name=f"{name}'s Org", slug=_slugify(name, user.id))
    db.add(org)
    await db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    await db.commit()
    return user


@router.post("/register", response_model=TokenPair, status_code=201)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    exists = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = await provision_user(db, body.email, body.name, hash_password(body.password))
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


# ── 第三方登录 SSO（P11）──

@router.get("/oauth/providers")
async def oauth_providers():
    """前端据此渲染可用的第三方登录按钮"""
    return {"providers": oauth.enabled_providers()}


@router.get("/oauth/{provider}/url")
async def oauth_url(provider: str, redirect_uri: str = Query(...)):
    if not oauth.enabled(provider):
        raise HTTPException(status_code=400, detail=f"{provider} login not configured")
    state = oauth.new_state()
    return {"authorize_url": await oauth.build_authorize_url(provider, redirect_uri, state), "state": state}


@router.post("/oauth/{provider}/exchange", response_model=TokenPair)
async def oauth_exchange(provider: str, body: OAuthExchangeIn, db: AsyncSession = Depends(get_db)):
    """用授权 code 换我方 JWT；首次登录自动建号 + 个人组织"""
    if not oauth.enabled(provider):
        raise HTTPException(status_code=400, detail=f"{provider} login not configured")
    try:
        info = await oauth.exchange(provider, body.code, body.redirect_uri)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth exchange failed: {e}")

    user = (await db.execute(select(User).where(User.email == info["email"]))).scalar_one_or_none()
    if user is None:
        # 无密码用户：置不可用随机哈希
        user = await provision_user(db, info["email"], info.get("name") or info["email"],
                                    hash_password(secrets.token_urlsafe(32)))
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/login", response_model=TokenPair)
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshIn, db: AsyncSession = Depends(get_db)):
    user_id = decode_token(body.refresh_token, expected_type="refresh")
    if user_id is None or await db.get(User, user_id) is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    return TokenPair(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
