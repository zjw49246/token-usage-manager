from fastapi import Header, HTTPException, Depends, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.config import settings
from app.models import User, Membership
from app.services.auth import verify_api_key
from app.services.user_auth import decode_token

# RBAC 角色层级：数值越大权限越高
ROLE_LEVEL = {"member": 1, "admin": 2, "owner": 3}


async def require_admin(authorization: str = Header(...)):
    """验证平台超管 token（bootstrap，用于平台级运维：供应商/目录管理等）"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return token


async def get_current_user(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> User:
    """验证 JWT，返回 User"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    user_id = decode_token(authorization.removeprefix("Bearer ").strip())
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_membership(
    org_id: int = Path(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Membership:
    """校验当前用户是 org 成员；超管视作 owner。返回 Membership（超管为虚拟对象）"""
    if user.is_superadmin:
        return Membership(org_id=org_id, user_id=user.id, role="owner")
    m = (
        await db.execute(
            select(Membership).where(Membership.org_id == org_id, Membership.user_id == user.id)
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    return m


def require_role(min_role: str):
    """org 内最低角色要求的依赖工厂：member < admin < owner"""

    async def _check(m: Membership = Depends(get_membership)) -> Membership:
        if ROLE_LEVEL[m.role] < ROLE_LEVEL[min_role]:
            raise HTTPException(status_code=403, detail=f"Requires role '{min_role}' or above")
        return m

    return _check


async def get_current_api_key(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """验证客户端 API Key，返回 ApiKey 对象"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    raw_key = authorization.removeprefix("Bearer ").strip()
    api_key = await verify_api_key(db, raw_key)
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key
