"""
配额检查服务：
- Token 总量、调用次数、模型白名单、时间区间 → 查数据库
- RPM（每分钟请求数） → 内存滑动窗口，不阻塞响应
"""
from collections import defaultdict, deque
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import ApiKey, UsageSummary, UsageRecord
import asyncio

# 内存 RPM 计数器：{api_key_id: deque of timestamps}
_rpm_windows: dict[int, deque] = defaultdict(deque)
_rpm_lock = asyncio.Lock()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def check_quota(db: AsyncSession, api_key: ApiKey, model: str) -> None:
    """
    校验配额，不通过则抛出 HTTPException。
    调用方保证 api_key.is_active 已校验。
    """
    now = _now_utc()

    # 1. 时间区间
    if api_key.valid_from and now < api_key.valid_from:
        raise HTTPException(status_code=403, detail="API key not yet valid")
    if api_key.valid_until and now > api_key.valid_until:
        raise HTTPException(status_code=403, detail="API key has expired")

    # 2. 模型白名单
    if api_key.allowed_models is not None and model not in api_key.allowed_models:
        raise HTTPException(status_code=403, detail=f"Model '{model}' not allowed for this key")

    # 3. Token / 调用次数上限（读 usage_summary）
    if api_key.max_total_tokens is not None or api_key.max_calls is not None:
        result = await db.execute(
            select(UsageSummary).where(UsageSummary.api_key_id == api_key.id)
        )
        summary = result.scalar_one_or_none()
        if summary:
            if api_key.max_total_tokens and summary.total_tokens_used >= api_key.max_total_tokens:
                raise HTTPException(status_code=429, detail="Token quota exceeded")
            if api_key.max_calls and summary.total_calls >= api_key.max_calls:
                raise HTTPException(status_code=429, detail="Call quota exceeded")

    # 4. RPM 限速（内存滑动窗口）
    if api_key.max_rpm is not None:
        async with _rpm_lock:
            window = _rpm_windows[api_key.id]
            cutoff = now.timestamp() - 60
            while window and window[0] < cutoff:
                window.popleft()
            if len(window) >= api_key.max_rpm:
                raise HTTPException(status_code=429, detail="Rate limit exceeded (RPM)")
            window.append(now.timestamp())


async def record_usage(
    db: AsyncSession,
    api_key_id: int,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    duration_ms: int | None,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    """写 usage_records + 更新 usage_summary，供后台 Task 调用"""
    # 写明细
    record = UsageRecord(
        api_key_id=api_key_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens or 0,
        duration_ms=duration_ms,
        status=status,
        error_message=error_message,
    )
    db.add(record)

    # upsert summary
    result = await db.execute(
        select(UsageSummary).where(UsageSummary.api_key_id == api_key_id)
    )
    summary = result.scalar_one_or_none()
    if summary is None:
        summary = UsageSummary(
            api_key_id=api_key_id,
            total_tokens_used=total_tokens or 0,
            total_calls=1,
            last_call_at=_now_utc(),
        )
        db.add(summary)
    else:
        summary.total_tokens_used += total_tokens or 0
        summary.total_calls += 1
        summary.last_call_at = _now_utc()

    await db.commit()
