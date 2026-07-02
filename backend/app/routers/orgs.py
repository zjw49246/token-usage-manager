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
from app.dependencies import get_current_user, get_membership, require_role, ROLE_LEVEL
from app.models import (
    User, Organization, Membership, ApiKey, UsageRecord, UsageSummary,
)
from app.schemas import (
    OrgCreate, OrgOut, MemberAdd, MemberUpdate, MemberOut,
    ApiKeyCreate, ApiKeyUpdate, ApiKeyOut, ApiKeyCreated,
    UsageSummaryOut, UsageRecordOut, UsageListOut, OverviewStats,
)
from app.services.auth import generate_api_key

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
    await db.commit()
    await db.refresh(org)
    out = OrgOut.model_validate(org)
    out.role = "owner"
    return out


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
        MemberOut(id=mem.id, user_id=u.id, email=u.email, name=u.name, role=mem.role, created_at=mem.created_at)
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
    mem = Membership(org_id=org_id, user_id=user.id, role=body.role)
    db.add(mem)
    await db.commit()
    await db.refresh(mem)
    return MemberOut(id=mem.id, user_id=user.id, email=user.email, name=user.name, role=mem.role, created_at=mem.created_at)


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
    # 不能把最后一个 owner 降级
    if mem.role == "owner" and body.role != "owner":
        owner_count = (
            await db.execute(
                select(func.count()).select_from(Membership)
                .where(Membership.org_id == org_id, Membership.role == "owner")
            )
        ).scalar_one()
        if owner_count <= 1:
            raise HTTPException(status_code=409, detail="Cannot demote the last owner")
    mem.role = body.role
    await db.commit()
    await db.refresh(mem)
    user = await db.get(User, user_id)
    return MemberOut(id=mem.id, user_id=user.id, email=user.email, name=user.name, role=mem.role, created_at=mem.created_at)


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
    keys = (await db.execute(select(ApiKey).where(ApiKey.org_id == org_id).order_by(ApiKey.created_at.desc()))).scalars().all()
    summaries = {s.api_key_id: s for s in (await db.execute(select(UsageSummary))).scalars().all()}
    return [_key_to_out(k, summaries.get(k.id)) for k in keys]


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
        max_rpm=body.max_rpm, max_cost_usd=body.max_cost_usd,
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
