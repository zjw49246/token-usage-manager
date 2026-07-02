"""组织 / 成员 / RBAC + org 隔离的 Key 与用量（P2 多租户）。

权限矩阵（org 内）：
- member：查看组织、成员、Key、用量
- admin ：+ 建/改/删 Key、加/删成员（不能动 owner、不能改成 owner）
- owner ：+ 改成员角色、删组织
超管（is_superadmin）对任意组织视作 owner。
"""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, get_membership, require_role, require_superadmin, ROLE_LEVEL
from app.models import (
    User, Organization, Membership, ApiKey, UsageRecord, UsageSummary, CreditTransaction,
)
from app.schemas import (
    OrgCreate, OrgOut, MemberAdd, MemberUpdate, MemberOut,
    ApiKeyCreate, ApiKeyUpdate, ApiKeyOut, ApiKeyCreated,
    UsageSummaryOut, UsageRecordOut, UsageListOut, OverviewStats,
    TrendPoint, TrendStats, KeyTokenShare,
    CreditTopup, CreditTransactionOut, CreditBalanceOut, CheckoutIn, CheckoutOut, PlaygroundIn,
)
from app.services.auth import generate_api_key
from app.services.credits import apply_credit
from app.services import payments
from app.services import router as model_router
from app.services.quota import check_quota
from app.config import settings

PLAYGROUND_KEY_NAME = "__playground__"

router = APIRouter(prefix="/orgs", tags=["orgs"])


def _now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _key_to_out(key: ApiKey, summary: UsageSummary | None = None) -> ApiKeyOut:
    data = ApiKeyOut.model_validate(key)
    if summary:
        data.usage = UsageSummaryOut(
            total_tokens_used=summary.total_tokens_used,
            total_calls=summary.total_calls,
            total_cost_usd=summary.total_cost_usd,
            last_call_at=summary.last_call_at,
        )
    return data


# ── 组织 ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[OrgOut])
async def my_orgs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """当前用户所属的组织（含角色）"""
    rows = (
        await db.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == user.id)
            .order_by(Organization.created_at)
        )
    ).all()
    result = []
    for org, role in rows:
        out = OrgOut.model_validate(org)
        out.role = role
        result.append(out)
    return result


@router.post("", response_model=OrgOut, status_code=201)
async def create_org(body: OrgCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    import re
    org = Organization(name=body.name, slug=re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-") + f"-{user.id}-{int(_now_utc().timestamp())}")
    db.add(org)
    await db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    if settings.welcome_credit_usd > 0:
        await apply_credit(db, org.id, settings.welcome_credit_usd, type="grant", ref="welcome", commit=False)
    await db.commit()
    await db.refresh(org)
    out = OrgOut.model_validate(org)
    out.role = "owner"
    return out


@router.patch("/{org_id}/pricing", response_model=OrgOut)
async def set_org_pricing(
    org_id: int, payload: dict,
    _sa: User = Depends(require_superadmin), db: AsyncSession = Depends(get_db),
):
    """超管设置组织价格倍率（>0；<1 折扣，>1 加价）"""
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    mult = payload.get("price_multiplier")
    if mult is None or float(mult) <= 0:
        raise HTTPException(status_code=400, detail="price_multiplier must be > 0")
    org.price_multiplier = float(mult)
    await db.commit()
    await db.refresh(org)
    return OrgOut.model_validate(org)


@router.get("/{org_id}", response_model=OrgOut)
async def get_org(org_id: int, m: Membership = Depends(get_membership), db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    out = OrgOut.model_validate(org)
    out.role = m.role
    return out


# ── 成员管理 ──────────────────────────────────────────────────────────────────

@router.get("/{org_id}/members", response_model=list[MemberOut])
async def list_members(org_id: int, m: Membership = Depends(get_membership), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.org_id == org_id)
            .order_by(Membership.created_at)
        )
    ).all()
    return [
        MemberOut(id=mem.id, user_id=u.id, email=u.email, name=u.name, role=mem.role,
                  budget_usd=mem.budget_usd, created_at=mem.created_at)
        for mem, u in rows
    ]


@router.post("/{org_id}/members", response_model=MemberOut, status_code=201)
async def add_member(
    org_id: int, body: MemberAdd,
    m: Membership = Depends(require_role("admin")), db: AsyncSession = Depends(get_db),
):
    if body.role == "owner" and ROLE_LEVEL[m.role] < ROLE_LEVEL["owner"]:
        raise HTTPException(status_code=403, detail="Only owner can grant owner role")
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found (must register first)")
    exists = (
        await db.execute(select(Membership).where(Membership.org_id == org_id, Membership.user_id == user.id))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Already a member")
    mem = Membership(org_id=org_id, user_id=user.id, role=body.role, budget_usd=body.budget_usd)
    db.add(mem)
    await db.commit()
    await db.refresh(mem)
    return MemberOut(id=mem.id, user_id=user.id, email=user.email, name=user.name, role=mem.role,
                     budget_usd=mem.budget_usd, created_at=mem.created_at)


@router.patch("/{org_id}/members/{user_id}", response_model=MemberOut)
async def update_member_role(
    org_id: int, user_id: int, body: MemberUpdate,
    m: Membership = Depends(require_role("owner")), db: AsyncSession = Depends(get_db),
):
    mem = (
        await db.execute(select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id))
    ).scalar_one_or_none()
    if mem is None:
        raise HTTPException(status_code=404, detail="Member not found")
    # 改角色：不能把最后一个 owner 降级
    if body.role is not None and mem.role == "owner" and body.role != "owner":
        owner_count = (
            await db.execute(
                select(func.count()).select_from(Membership)
                .where(Membership.org_id == org_id, Membership.role == "owner")
            )
        ).scalar_one()
        if owner_count <= 1:
            raise HTTPException(status_code=409, detail="Cannot demote the last owner")
    if body.role is not None:
        mem.role = body.role
    if body.budget_usd is not None:
        mem.budget_usd = body.budget_usd or None  # 0 视为不限
    await db.commit()
    await db.refresh(mem)
    user = await db.get(User, user_id)
    return MemberOut(id=mem.id, user_id=user.id, email=user.email, name=user.name, role=mem.role,
                     budget_usd=mem.budget_usd, created_at=mem.created_at)


@router.delete("/{org_id}/members/{user_id}", status_code=204)
async def remove_member(
    org_id: int, user_id: int,
    m: Membership = Depends(require_role("admin")), db: AsyncSession = Depends(get_db),
):
    mem = (
        await db.execute(select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id))
    ).scalar_one_or_none()
    if mem is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if mem.role == "owner":
        owner_count = (
            await db.execute(
                select(func.count()).select_from(Membership)
                .where(Membership.org_id == org_id, Membership.role == "owner")
            )
        ).scalar_one()
        if owner_count <= 1:
            raise HTTPException(status_code=409, detail="Cannot remove the last owner")
    await db.delete(mem)
    await db.commit()


# ── org 隔离的 API Key CRUD ────────────────────────────────────────────────────

async def _get_org_key(db: AsyncSession, org_id: int, key_id: int) -> ApiKey:
    key = await db.get(ApiKey, key_id)
    if key is None or key.org_id != org_id:
        raise HTTPException(status_code=404, detail="Key not found")
    return key


@router.get("/{org_id}/keys", response_model=list[ApiKeyOut])
async def list_org_keys(org_id: int, m: Membership = Depends(get_membership), db: AsyncSession = Depends(get_db)):
    keys = (await db.execute(
        select(ApiKey).where(ApiKey.org_id == org_id, ApiKey.name != PLAYGROUND_KEY_NAME)
        .order_by(ApiKey.created_at.desc())
    )).scalars().all()
    summaries = {s.api_key_id: s for s in (await db.execute(select(UsageSummary))).scalars().all()}
    return [_key_to_out(k, summaries.get(k.id)) for k in keys]


@router.get("/{org_id}/keys/{key_id}", response_model=ApiKeyOut)
async def get_org_key(org_id: int, key_id: int, m: Membership = Depends(get_membership), db: AsyncSession = Depends(get_db)):
    key = await _get_org_key(db, org_id, key_id)
    summary = await db.get(UsageSummary, key_id)
    return _key_to_out(key, summary)


@router.post("/{org_id}/keys", response_model=ApiKeyCreated, status_code=201)
async def create_org_key(
    org_id: int, body: ApiKeyCreate,
    m: Membership = Depends(require_role("admin")),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    raw_key, key_hash, key_prefix = generate_api_key()
    key = ApiKey(
        key_hash=key_hash, key_prefix=key_prefix, name=body.name,
        org_id=org_id, created_by_user_id=user.id,
        allowed_models=body.allowed_models,
        max_total_tokens=body.max_total_tokens, max_calls=body.max_calls,
        max_rpm=body.max_rpm, model_rpm=body.model_rpm, max_cost_usd=body.max_cost_usd,
        allowed_ips=body.allowed_ips,
        valid_from=body.valid_from, valid_until=body.valid_until,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    base = ApiKeyOut.model_validate(key)
    return ApiKeyCreated(**base.model_dump(), key=raw_key)


@router.patch("/{org_id}/keys/{key_id}", response_model=ApiKeyOut)
async def update_org_key(
    org_id: int, key_id: int, body: ApiKeyUpdate,
    m: Membership = Depends(require_role("admin")), db: AsyncSession = Depends(get_db),
):
    key = await _get_org_key(db, org_id, key_id)
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(key, field, val)
    key.updated_at = _now_utc()
    await db.commit()
    await db.refresh(key)
    summary = await db.get(UsageSummary, key_id)
    return _key_to_out(key, summary)


@router.delete("/{org_id}/keys/{key_id}", status_code=204)
async def delete_org_key(
    org_id: int, key_id: int,
    m: Membership = Depends(require_role("admin")), db: AsyncSession = Depends(get_db),
):
    key = await _get_org_key(db, org_id, key_id)
    await db.delete(key)
    await db.commit()


@router.get("/{org_id}/keys/{key_id}/usage", response_model=UsageListOut)
async def org_key_usage(
    org_id: int, key_id: int,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    m: Membership = Depends(get_membership), db: AsyncSession = Depends(get_db),
):
    await _get_org_key(db, org_id, key_id)
    filters = [UsageRecord.api_key_id == key_id]
    if status:
        filters.append(UsageRecord.status == status)
    total = (await db.execute(select(func.count()).select_from(UsageRecord).where(and_(*filters)))).scalar_one()
    records = (
        await db.execute(
            select(UsageRecord).where(and_(*filters))
            .order_by(UsageRecord.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return UsageListOut(
        items=[UsageRecordOut.model_validate(r) for r in records],
        total=total, page=page, page_size=page_size,
    )


# ── Playground（站内测试）────────────────────────────────────────────────────────

async def _playground_key(db: AsyncSession, org_id: int, user_id: int) -> ApiKey:
    """惰性创建组织隐藏 Playground Key（复用配额/计费/记账，不在 Key 列表显示）"""
    key = (
        await db.execute(select(ApiKey).where(ApiKey.org_id == org_id, ApiKey.name == PLAYGROUND_KEY_NAME))
    ).scalar_one_or_none()
    if key is None:
        _raw, key_hash, key_prefix = generate_api_key()
        key = ApiKey(key_hash=key_hash, key_prefix=key_prefix, name=PLAYGROUND_KEY_NAME,
                     org_id=org_id, created_by_user_id=user_id, is_active=True)
        db.add(key)
        await db.commit()
        await db.refresh(key)
    return key


@router.post("/{org_id}/playground/chat")
async def playground_chat(
    org_id: int, body: PlaygroundIn,
    m: Membership = Depends(get_membership),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """站内试聊：用组织隐藏 Key 走真实路由（计入组织用量/额度），非流式返回。"""
    key = await _playground_key(db, org_id, user.id)
    routes = await model_router.resolve_routes(db, body.model)
    await check_quota(db, key, body.model)
    payload = {"model": body.model, "messages": body.messages, "stream": False}
    if body.temperature is not None:
        payload["temperature"] = body.temperature
    if body.max_tokens is not None:
        payload["max_tokens"] = body.max_tokens
    return await model_router.route_chat_completion(key, routes, payload)


# ── 计费 / 额度 ────────────────────────────────────────────────────────────────

@router.get("/{org_id}/credits", response_model=CreditBalanceOut)
async def get_credits(org_id: int, m: Membership = Depends(get_membership), db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    txns = (
        await db.execute(
            select(CreditTransaction).where(CreditTransaction.org_id == org_id)
            .order_by(CreditTransaction.created_at.desc()).limit(100)
        )
    ).scalars().all()
    return CreditBalanceOut(
        balance_usd=round(org.credit_balance_usd, 6),
        transactions=[CreditTransactionOut.model_validate(t) for t in txns],
    )


@router.post("/{org_id}/credits", response_model=CreditBalanceOut)
async def topup_credits(
    org_id: int, body: CreditTopup,
    m: Membership = Depends(require_role("owner")), db: AsyncSession = Depends(get_db),
):
    """手动充值（owner）。真实支付走 /credits/checkout。"""
    await apply_credit(db, org_id, body.amount_usd, type="topup", ref=body.note or "manual")
    return await get_credits(org_id, m, db)


@router.post("/{org_id}/credits/checkout", response_model=CheckoutOut)
async def create_checkout(
    org_id: int, body: CheckoutIn,
    m: Membership = Depends(require_role("owner")), db: AsyncSession = Depends(get_db),
):
    """发起 Stripe 在线充值，返回支付跳转 URL（支付完成由 webhook 入账）。"""
    if not payments.stripe_enabled():
        raise HTTPException(status_code=400, detail="Stripe not configured; use manual top-up")
    url = payments.create_checkout_session(org_id, body.amount_usd, body.success_url, body.cancel_url)
    return CheckoutOut(checkout_url=url)


# ── org 隔离的统计 ─────────────────────────────────────────────────────────────

@router.get("/{org_id}/stats/overview", response_model=OverviewStats)
async def org_overview(org_id: int, m: Membership = Depends(get_membership), db: AsyncSession = Depends(get_db)):
    today_start = _now_utc().replace(hour=0, minute=0, second=0, microsecond=0)

    async def scalar(stmt):
        return (await db.execute(stmt)).scalar_one()

    # 组织累计（跨该 org 所有 Key 的 summary）
    org_key_ids = select(ApiKey.id).where(ApiKey.org_id == org_id).scalar_subquery()
    total_tokens = await scalar(
        select(func.coalesce(func.sum(UsageSummary.total_tokens_used), 0))
        .where(UsageSummary.api_key_id.in_(org_key_ids))
    )
    total_calls = await scalar(
        select(func.coalesce(func.sum(UsageSummary.total_calls), 0))
        .where(UsageSummary.api_key_id.in_(org_key_ids))
    )
    total_cost = await scalar(
        select(func.coalesce(func.sum(UsageSummary.total_cost_usd), 0.0))
        .where(UsageSummary.api_key_id.in_(org_key_ids))
    )
    today_tokens = await scalar(
        select(func.coalesce(func.sum(UsageRecord.total_tokens), 0))
        .where(UsageRecord.org_id == org_id, UsageRecord.created_at >= today_start)
    )
    today_cost = await scalar(
        select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0))
        .where(UsageRecord.org_id == org_id, UsageRecord.created_at >= today_start)
    )
    today_calls = await scalar(
        select(func.count()).select_from(UsageRecord)
        .where(UsageRecord.org_id == org_id, UsageRecord.created_at >= today_start)
    )
    active_keys = await scalar(
        select(func.count()).select_from(ApiKey).where(ApiKey.org_id == org_id, ApiKey.is_active.is_(True))
    )
    total_keys = await scalar(select(func.count()).select_from(ApiKey).where(ApiKey.org_id == org_id))

    return OverviewStats(
        total_tokens=total_tokens, today_tokens=today_tokens,
        total_calls=total_calls, today_calls=today_calls,
        total_cost_usd=round(total_cost, 6), today_cost_usd=round(today_cost, 6),
        active_keys=active_keys, total_keys=total_keys,
    )


@router.get("/{org_id}/stats/trend", response_model=TrendStats)
async def org_trend(
    org_id: int,
    granularity: str = Query("day", pattern="^(hour|day)$"),
    days: int = Query(7, ge=1, le=30),
    m: Membership = Depends(get_membership), db: AsyncSession = Depends(get_db),
):
    from collections import defaultdict
    since = _now_utc() - timedelta(days=days)
    rows = (
        await db.execute(
            select(UsageRecord.created_at, UsageRecord.total_tokens, UsageRecord.cost_usd)
            .where(UsageRecord.org_id == org_id, UsageRecord.created_at >= since)
            .order_by(UsageRecord.created_at)
        )
    ).all()
    buckets: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "calls": 0})
    for created_at, tokens, _cost in rows:
        key = created_at.strftime("%Y-%m-%d %H:00") if granularity == "hour" else created_at.strftime("%Y-%m-%d")
        buckets[key]["tokens"] += tokens or 0
        buckets[key]["calls"] += 1
    points = [TrendPoint(time=k, tokens=v["tokens"], calls=v["calls"]) for k, v in sorted(buckets.items())]
    return TrendStats(points=points)


@router.get("/{org_id}/stats/key-shares", response_model=list[KeyTokenShare])
async def org_key_shares(org_id: int, m: Membership = Depends(get_membership), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(ApiKey.name, ApiKey.key_prefix, UsageSummary.total_tokens_used)
            .join(UsageSummary, ApiKey.id == UsageSummary.api_key_id)
            .where(ApiKey.org_id == org_id)
            .order_by(UsageSummary.total_tokens_used.desc())
        )
    ).all()
    return [KeyTokenShare(name=n, key_prefix=p, tokens=t) for n, p, t in rows]


# ── 组织级请求日志 + CSV 导出（P25）────────────────────────────────────────────

def _usage_filters(org_id: int, model: str | None, status: str | None,
                   start_time: datetime | None, end_time: datetime | None):
    filters = [UsageRecord.org_id == org_id]
    if model:
        filters.append(UsageRecord.model == model)
    if status:
        filters.append(UsageRecord.status == status)
    if start_time:
        filters.append(UsageRecord.created_at >= start_time)
    if end_time:
        filters.append(UsageRecord.created_at <= end_time)
    return filters


@router.get("/{org_id}/usage", response_model=UsageListOut)
async def org_usage(
    org_id: int,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
    model: str | None = Query(None), status: str | None = Query(None),
    start_time: datetime | None = Query(None), end_time: datetime | None = Query(None),
    m: Membership = Depends(get_membership), db: AsyncSession = Depends(get_db),
):
    """组织全量请求日志（跨所有 Key），支持按模型/状态/时间过滤"""
    filters = _usage_filters(org_id, model, status, start_time, end_time)
    total = (await db.execute(select(func.count()).select_from(UsageRecord).where(and_(*filters)))).scalar_one()
    records = (
        await db.execute(
            select(UsageRecord).where(and_(*filters))
            .order_by(UsageRecord.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return UsageListOut(
        items=[UsageRecordOut.model_validate(r) for r in records],
        total=total, page=page, page_size=page_size,
    )


@router.get("/{org_id}/usage/export")
async def org_usage_export(
    org_id: int,
    model: str | None = Query(None), status: str | None = Query(None),
    start_time: datetime | None = Query(None), end_time: datetime | None = Query(None),
    m: Membership = Depends(get_membership), db: AsyncSession = Depends(get_db),
):
    """导出组织请求日志为 CSV（最多 5 万行）"""
    import csv
    import io
    from fastapi.responses import Response

    filters = _usage_filters(org_id, model, status, start_time, end_time)
    records = (
        await db.execute(
            select(UsageRecord).where(and_(*filters))
            .order_by(UsageRecord.created_at.desc()).limit(50000)
        )
    ).scalars().all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time", "model", "provider", "input_tokens", "output_tokens",
                "total_tokens", "cost_usd", "cached", "duration_ms", "status", "error"])
    for r in records:
        w.writerow([r.created_at.isoformat(), r.model, r.provider or "", r.input_tokens or "",
                    r.output_tokens or "", r.total_tokens or "", r.cost_usd if r.cost_usd is not None else "",
                    int(r.cached), r.duration_ms or "", r.status, (r.error_message or "").replace("\n", " ")])
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=usage-org{org_id}.csv"},
    )
