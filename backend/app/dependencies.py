from fastapi import Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.config import settings
from app.services.auth import verify_api_key


async def require_admin(authorization: str = Header(...)):
    """验证管理员 token"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return token


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
