"""响应缓存（P7）：相同请求去重复用。

- 默认进程内内存缓存（带 TTL）；配置 REDIS_URL 则用 Redis（多副本共享）。
- 缓存键 = 请求内容（model + messages + 采样参数）的 sha256，全局内容寻址（跨租户去重省钱）。
- 只缓存非流式 chat 响应。命中按 cache_hit_cost_multiplier 折算成本计费。
"""
import hashlib
import json
import time
from typing import Any

from app.config import settings

# 参与缓存键的请求字段（决定"同一请求"）
_KEY_FIELDS = ("model", "messages", "temperature", "top_p", "max_tokens", "stop", "n", "tools", "tool_choice", "response_format")


def cache_key(model_id: str, body: dict) -> str:
    payload = {"model": model_id}
    for f in _KEY_FIELDS:
        if f in body and body[f] is not None:
            payload[f] = body[f]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return "resp:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


class _MemoryCache:
    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}

    async def get(self, key: str):
        item = self._store.get(key)
        if item is None:
            return None
        expire, value = item
        if expire and expire < time.time():
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int):
        self._store[key] = (time.time() + ttl if ttl else 0, value)

    async def clear(self):
        self._store.clear()


class _RedisCache:
    def __init__(self, url: str):
        import redis.asyncio as redis  # 延迟导入，未装 redis 也能跑内存缓存
        self._r = redis.from_url(url, decode_responses=True)

    async def get(self, key: str):
        raw = await self._r.get(key)
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: Any, ttl: int):
        await self._r.set(key, json.dumps(value, ensure_ascii=False), ex=ttl or None)

    async def clear(self):
        await self._r.flushdb()


_cache = None


def get_cache():
    """惰性单例：按配置选内存或 Redis"""
    global _cache
    if _cache is None:
        if settings.redis_url:
            try:
                _cache = _RedisCache(settings.redis_url)
            except Exception:
                _cache = _MemoryCache()
        else:
            _cache = _MemoryCache()
    return _cache


def reset_cache():
    """测试用：重置单例"""
    global _cache
    _cache = None
