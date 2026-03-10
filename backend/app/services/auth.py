import hashlib
import secrets
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import ApiKey


def generate_api_key() -> tuple[str, str, str]:
    """生成 API Key，返回 (raw_key, key_hash, key_prefix)"""
    raw_key = "tum_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]
    return raw_key, key_hash, key_prefix


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def verify_api_key(db: AsyncSession, raw_key: str) -> ApiKey | None:
    """校验 API Key，返回 ApiKey 对象或 None"""
    key_hash = hash_key(raw_key)
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    return result.scalar_one_or_none()
