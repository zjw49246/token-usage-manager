"""用户鉴权服务（P2 多租户）：bcrypt 密码哈希 + JWT 签发/校验"""
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"


def _pw_bytes(password: str) -> bytes:
    # bcrypt 上限 72 字节，超出部分静默截断（与主流实现一致）
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_pw_bytes(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _create_token(user_id: int, token_type: str, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_access_token(user_id: int) -> str:
    return _create_token(user_id, "access", timedelta(minutes=settings.jwt_access_ttl_minutes))


def create_refresh_token(user_id: int) -> str:
    return _create_token(user_id, "refresh", timedelta(days=settings.jwt_refresh_ttl_days))


def decode_token(token: str, expected_type: str = "access") -> int | None:
    """校验并解出 user_id；无效/过期/类型不符返回 None"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None
