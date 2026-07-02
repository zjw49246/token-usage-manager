from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.database import get_db
from app.dependencies import require_admin
from app.models import ApiKey, UsageRecord, UsageSummary, User
from app.schemas import (
    ApiKeyCreate, ApiKeyUpdate, ApiKeyOut, ApiKeyCreated,
    UsageSummaryOut, UsageRecordOut, UsageListOut,
    OverviewStats, TrendPoint, TrendStats, KeyTokenShare,
)
from app.services.auth import generate_api_key

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/superadmin")
async def promote_superadmin(payload: dict, db: AsyncSession = Depends(get_db)):
    """用平台 ADMIN_TOKEN 把某个已注册用户提升为超管（bootstrap 通道/供应商管理）。

    body: {"email": "..."}
    """
    email = (payload or {}).get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Missing 'email'")
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found (must register first)")
    user.is_superadmin = True
    await db.commit()
    return {"email": email, "is_superadmin": True}


def _now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _key_to_out(key: ApiKey, summary: UsageSummary | None = None) -> ApiKeyOut:
    data = ApiKeyOut.model_validate(key)
    if summary:
        data.usage = UsageSummaryOut(
            total_tokens_used=summary.total_tokens_used,
            total_calls=summary.total_calls,
            last_call_at=summary.last_call_at,
        )
    return data


# ── API Key CRUD ──────────────────────────────────────────────────────────────

@router.post("/keys", response_model=ApiKeyCreated, status_code=201)
async def create_key(body: ApiKeyCreate, db: AsyncSession = Depends(get_db)):
    raw_key, key_hash, key_prefix = generate_api_key()
    key = ApiKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=body.name,
        allowed_models=body.allowed_models,
        max_total_tokens=body.max_total_tokens,
        max_calls=body.max_calls,
        max_rpm=body.max_rpm,
        max_cost_usd=body.max_cost_usd,
        allowed_ips=body.allowed_ips,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    base = ApiKeyOut.model_validate(key)
    return ApiKeyCreated(**base.model_dump(), key=raw_key)


@router.get("/keys", response_model=list[ApiKeyOut])
async def list_keys(db: AsyncSession = Depends(get_db)):
    keys_result = await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    keys = keys_result.scalars().all()

    summaries_result = await db.execute(select(UsageSummary))
    summaries = {s.api_key_id: s for s in summaries_result.scalars().all()}

    return [_key_to_out(k, summaries.get(k.id)) for k in keys]


@router.get("/keys/{key_id}", response_model=ApiKeyOut)
async def get_key(key_id: int, db: AsyncSession = Depends(get_db)):
    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    summary = await db.get(UsageSummary, key_id)
    return _key_to_out(key, summary)


@router.patch("/keys/{key_id}", response_model=ApiKeyOut)
async def update_key(key_id: int, body: ApiKeyUpdate, db: AsyncSession = Depends(get_db)):
    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(key, field, val)
    key.updated_at = _now_utc()
    await db.commit()
    await db.refresh(key)
    summary = await db.get(UsageSummary, key_id)
    return _key_to_out(key, summary)


@router.delete("/keys/{key_id}", status_code=204)
async def delete_key(key_id: int, db: AsyncSession = Depends(get_db)):
    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    await db.delete(key)
    await db.commit()


# ── 用量明细 ──────────────────────────────────────────────────────────────────

@router.get("/keys/{key_id}/usage", response_model=UsageListOut)
async def get_key_usage(
    key_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")

    filters = [UsageRecord.api_key_id == key_id]
    if status:
        filters.append(UsageRecord.status == status)
    if start_time:
        filters.append(UsageRecord.created_at >= start_time)
    if end_time:
        filters.append(UsageRecord.created_at <= end_time)

    count_result = await db.execute(
        select(func.count()).select_from(UsageRecord).where(and_(*filters))
    )
    total = count_result.scalar_one()

    records_result = await db.execute(
        select(UsageRecord)
        .where(and_(*filters))
        .order_by(UsageRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    records = records_result.scalars().all()

    return UsageListOut(
        items=[UsageRecordOut.model_validate(r) for r in records],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── 统计 ──────────────────────────────────────────────────────────────────────

@router.get("/stats/overview", response_model=OverviewStats)
async def get_overview(db: AsyncSession = Depends(get_db)):
    today_start = _now_utc().replace(hour=0, minute=0, second=0, microsecond=0)

    total_tokens = await db.execute(
        select(func.coalesce(func.sum(UsageSummary.total_tokens_used), 0))
    )
    today_tokens = await db.execute(
        select(func.coalesce(func.sum(UsageRecord.total_tokens), 0))
        .where(UsageRecord.created_at >= today_start)
    )
    total_calls = await db.execute(
        select(func.coalesce(func.sum(UsageSummary.total_calls), 0))
    )
    today_calls = await db.execute(
        select(func.count()).select_from(UsageRecord).where(UsageRecord.created_at >= today_start)
    )
    active_keys = await db.execute(
        select(func.count()).select_from(ApiKey).where(ApiKey.is_active == True)
    )
    total_keys = await db.execute(select(func.count()).select_from(ApiKey))

    return OverviewStats(
        total_tokens=total_tokens.scalar_one(),
        today_tokens=today_tokens.scalar_one(),
        total_calls=total_calls.scalar_one(),
        today_calls=today_calls.scalar_one(),
        active_keys=active_keys.scalar_one(),
        total_keys=total_keys.scalar_one(),
    )


@router.get("/stats/trend", response_model=TrendStats)
async def get_trend(
    granularity: str = Query("day", pattern="^(hour|day)$"),
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    since = _now_utc() - timedelta(days=days)
    records_result = await db.execute(
        select(UsageRecord.created_at, UsageRecord.total_tokens)
        .where(UsageRecord.created_at >= since)
        .order_by(UsageRecord.created_at)
    )
    records = records_result.all()

    # 按时间粒度聚合（Python 侧，记录量不大）
    from collections import defaultdict
    buckets: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "calls": 0})
    for created_at, tokens in records:
        if granularity == "hour":
            key = created_at.strftime("%Y-%m-%d %H:00")
        else:
            key = created_at.strftime("%Y-%m-%d")
        buckets[key]["tokens"] += tokens or 0
        buckets[key]["calls"] += 1

    points = [TrendPoint(time=k, tokens=v["tokens"], calls=v["calls"]) for k, v in sorted(buckets.items())]
    return TrendStats(points=points)


@router.get("/stats/key-shares", response_model=list[KeyTokenShare])
async def get_key_shares(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ApiKey.name, ApiKey.key_prefix, UsageSummary.total_tokens_used)
        .join(UsageSummary, ApiKey.id == UsageSummary.api_key_id)
        .order_by(UsageSummary.total_tokens_used.desc())
    )
    return [
        KeyTokenShare(name=name, key_prefix=prefix, tokens=tokens)
        for name, prefix, tokens in result.all()
    ]
