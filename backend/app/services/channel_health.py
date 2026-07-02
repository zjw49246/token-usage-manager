"""通道健康巡检（P28）：单通道连通测试 + 定时巡检所有通道。"""
import asyncio
import time

import litellm
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Channel, ModelCatalog, Provider


async def test_channel_conn(db, ch: Channel) -> dict:
    """对通道做一次最小连通测试，更新 status（不计入 success/error 计数——那是真实流量的口径）。"""
    from app.services.router import _resolve_env_credential

    if not ch.models:
        return {"ok": False, "latency_ms": 0, "model": None, "error": "channel serves no models"}
    model_id = ch.models[0]
    row = (
        await db.execute(
            select(ModelCatalog, Provider)
            .join(Provider, Provider.id == ModelCatalog.provider_id)
            .where(ModelCatalog.model_id == model_id)
        )
    ).first()
    if row is None:
        return {"ok": False, "latency_ms": 0, "model": model_id, "error": "model not in catalog"}
    catalog, provider = row
    upstream = (ch.model_map or {}).get(model_id) or catalog.litellm_model
    api_key = ch.api_key or _resolve_env_credential(provider.credential_env)
    api_base = ch.api_base or provider.api_base

    start = time.time()
    ok, error = True, None
    try:
        kwargs = {"model": upstream, "timeout": 30}
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base
        if catalog.mode == "embedding":
            await litellm.aembedding(input="ping", **kwargs)
        else:
            await litellm.acompletion(messages=[{"role": "user", "content": "ping"}], max_tokens=1, **kwargs)
    except Exception as e:
        ok, error = False, str(e)[:300]

    ch.status = "active" if ok else "error"
    await db.commit()
    return {"ok": ok, "latency_ms": int((time.time() - start) * 1000), "model": model_id, "error": error}


async def test_all_channels() -> list[dict]:
    """巡检所有启用通道，返回各自结果。"""
    async with AsyncSessionLocal() as db:
        channels = (await db.execute(select(Channel).where(Channel.enabled.is_(True)))).scalars().all()
        results = []
        for ch in channels:
            r = await test_channel_conn(db, ch)
            r["channel_id"] = ch.id
            r["name"] = ch.name
            results.append(r)
        return results


async def health_check_loop():
    """后台定时巡检（channel_health_check_interval>0 时由 lifespan 启动）。"""
    interval = settings.channel_health_check_interval
    while True:
        await asyncio.sleep(interval)
        try:
            await test_all_channels()
        except Exception:
            pass
