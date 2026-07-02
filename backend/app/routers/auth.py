"""用户鉴权路由（P2 多租户）：注册 / 登录 / 刷新 / 当前用户"""
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Organization, Membership
from app.schemas import RegisterIn, LoginIn, RefreshIn, TokenPair, UserOut
from app.services.user_auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(name: str, suffix: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"
    return f"{base}-{suffix}"


@router.post("/register", response_model=TokenPair, status_code=201)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    exists = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(email=body.email, password_hash=hash_password(body.password), name=body.name)
    db.add(user)
    await db.flush()

    # 注册即建个人组织，用户为 owner
    org = Organization(name=f"{body.name}'s Org", slug=_slugify(body.name, user.id))
    db.add(org)
    await db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    await db.commit()

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
