"""
配额检查服务：
- 时间区间、模型白名单 → 内存字段判断
- 调用次数 → **请求前原子预扣**（UPDATE ... WHERE total_calls < max_calls），杜绝并发绕过
- Token 总量 → 请求前尽力预检 + 响应后原子累加（token 数须等上游返回，故为最终一致）
- RPM（每分钟请求数） → 内存滑动窗口

关键点：调用次数在转发前就用一条带条件的原子 UPDATE 抢占额度，
并发请求不会再读到过期的 usage_summary，因此不会集体绕过配额。
"""
from collections import defaultdict, deque
from datetime import datetime, timezone
import asyncio

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func as sqlfunc

from app.config import settings
from app.models import ApiKey, UsageSummary, UsageRecord, Organization, Membership
from app.services.credits import apply_credit

# 内存 RPM 计数器：{api_key_id: deque of timestamps}
_rpm_windows: dict[int, deque] = defaultdict(deque)
# 按模型 RPM 计数器：{(api_key_id, model): deque}
_model_rpm_windows: dict[tuple, deque] = defaultdict(deque)
_rpm_lock = asyncio.Lock()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _ensure_summary(db: AsyncSession, api_key_id: int) -> None:
    """幂等地保证 usage_summary 行存在（原子 INSERT ... ON CONFLICT DO NOTHING）。

    替代原先 record_usage 里“先 SELECT 再 INSERT”的写法——那种写法在并发首次
    记账时会撞 UNIQUE 约束抛 IntegrityError（且被后台 task 吞掉，导致丢数据）。
    """
    stmt = (
        sqlite_insert(UsageSummary)
        .values(api_key_id=api_key_id, total_tokens_used=0, total_calls=0)
        .on_conflict_do_nothing(index_elements=["api_key_id"])
    )
    await db.execute(stmt)
    await db.commit()


async def check_quota(db: AsyncSession, api_key: ApiKey, model: str) -> None:
    """
    校验配额，不通过则抛出 HTTPException。
    通过时会**原子预扣一次调用额度**（total_calls += 1）。
    调用方保证 api_key.is_active 已校验。
    """
    now = _now_utc()

    # 1. 时间区间（只读判断，不消耗额度）
    if api_key.valid_from and now < api_key.valid_from:
        raise HTTPException(status_code=403, detail="API key not yet valid")
    if api_key.valid_until and now > api_key.valid_until:
        raise HTTPException(status_code=403, detail="API key has expired")

    # 2. 模型白名单（只读判断）
    if api_key.allowed_models is not None and model not in api_key.allowed_models:
        raise HTTPException(status_code=403, detail=f"Model '{model}' not allowed for this key")

    # 2.5 组织额度闸门：余额 <= 0 拒绝（预付费模式）
    if settings.enforce_credit_balance and api_key.org_id is not None:
        balance = await db.scalar(
            select(Organization.credit_balance_usd).where(Organization.id == api_key.org_id)
        )
        if balance is not None and balance <= 0:
            raise HTTPException(status_code=402, detail="Insufficient credits, please top up")

    # 2.6 成员级预算：该 Key 创建者在本组织的累计消费不得超过其 budget_usd
    if api_key.org_id is not None and api_key.created_by_user_id is not None:
        budget = await db.scalar(
            select(Membership.budget_usd).where(
                Membership.org_id == api_key.org_id,
                Membership.user_id == api_key.created_by_user_id,
            )
        )
        if budget is not None:
            spent = await db.scalar(
                select(sqlfunc.coalesce(sqlfunc.sum(UsageSummary.total_cost_usd), 0.0))
                .select_from(UsageSummary)
                .join(ApiKey, ApiKey.id == UsageSummary.api_key_id)
                .where(
                    ApiKey.org_id == api_key.org_id,
                    ApiKey.created_by_user_id == api_key.created_by_user_id,
                )
            )
            if spent is not None and spent >= budget:
                raise HTTPException(status_code=429, detail="Member budget exceeded")

    # 3. 保证 summary 行存在（后续原子操作依赖它）
    await _ensure_summary(db, api_key.id)

    # 4. Token 总量 / USD 成本：尽力预检（真实用量须等上游返回，故只能做到最终一致）
    if api_key.max_total_tokens is not None or getattr(api_key, "max_cost_usd", None) is not None:
        row = (
            await db.execute(
                select(UsageSummary.total_tokens_used, UsageSummary.total_cost_usd)
                .where(UsageSummary.api_key_id == api_key.id)
            )
        ).first()
        if row is not None:
            if api_key.max_total_tokens is not None and row.total_tokens_used >= api_key.max_total_tokens:
                raise HTTPException(status_code=429, detail="Token quota exceeded")
            if api_key.max_cost_usd is not None and row.total_cost_usd >= api_key.max_cost_usd:
                raise HTTPException(status_code=429, detail="Cost quota exceeded (USD)")

    # 5. RPM 限速（内存滑动窗口）——放在预扣之前，
    #    这样被限速拒绝的请求不会白白消耗一次调用额度
    model_rpm = (getattr(api_key, "model_rpm", None) or {}).get(model)
    if api_key.max_rpm is not None or model_rpm is not None:
        async with _rpm_lock:
            cutoff = now.timestamp() - 60
            ts = now.timestamp()
            # 全局 RPM
            if api_key.max_rpm is not None:
                window = _rpm_windows[api_key.id]
                while window and window[0] < cutoff:
                    window.popleft()
                if len(window) >= api_key.max_rpm:
                    raise HTTPException(status_code=429, detail="Rate limit exceeded (RPM)")
            # 按模型 RPM
            if model_rpm is not None:
                mwindow = _model_rpm_windows[(api_key.id, model)]
                while mwindow and mwindow[0] < cutoff:
                    mwindow.popleft()
                if len(mwindow) >= model_rpm:
                    raise HTTPException(status_code=429, detail=f"Rate limit exceeded for model '{model}' (RPM)")
            # 通过后再入窗（避免任一限流触发时污染另一窗口）
            if api_key.max_rpm is not None:
                _rpm_windows[api_key.id].append(ts)
            if model_rpm is not None:
                _model_rpm_windows[(api_key.id, model)].append(ts)

    # 6. 调用次数：原子预扣。带条件的 UPDATE，rowcount==0 说明已达上限。
    #    每个通过校验的请求恰好抢占一个额度，杜绝“事后异步记账”导致的并发绕过。
    stmt = (
        update(UsageSummary)
        .where(UsageSummary.api_key_id == api_key.id)
        .values(total_calls=UsageSummary.total_calls + 1, last_call_at=now)
    )
    if api_key.max_calls is not None:
        stmt = stmt.where(UsageSummary.total_calls < api_key.max_calls)
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=429, detail="Call quota exceeded")


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
    *,
    provider: str | None = None,
    cost_usd: float | None = None,
    org_id: int | None = None,
    cached: bool = False,
    cached_tokens: int | None = None,
) -> None:
    """写 usage_records 明细 + 原子累加 token/cost 用量，供后台 Task 调用。

    注意：调用次数（total_calls）已在 check_quota 里预扣，这里**不再重复计数**，
    只负责补记 token 数与明细。即便本函数因进程重启等原因未执行，
    调用额度也已被正确扣减，不会被绕过。
    """
    # 保证 summary 行存在（防御性；正常流程 check_quota 已建好）
    await _ensure_summary(db, api_key_id)

    # 组织价格倍率（P23）：按组织折算成本（在缓存折算之上再乘）
    if org_id is not None and cost_usd:
        mult = await db.scalar(select(Organization.price_multiplier).where(Organization.id == org_id))
        if mult is not None and mult != 1.0:
            cost_usd = round(cost_usd * mult, 8)

    # 写明细
    record = UsageRecord(
        api_key_id=api_key_id,
        org_id=org_id,
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens or 0,
        cost_usd=cost_usd,
        cached=cached,
        cached_tokens=cached_tokens,
        duration_ms=duration_ms,
        status=status,
        error_message=error_message,
    )
    db.add(record)

    # 原子累加 token / cost（避免 read-modify-write 竞态）
    await db.execute(
        update(UsageSummary)
        .where(UsageSummary.api_key_id == api_key_id)
        .values(
            total_tokens_used=UsageSummary.total_tokens_used + (total_tokens or 0),
            total_cost_usd=UsageSummary.total_cost_usd + (cost_usd or 0.0),
            last_call_at=_now_utc(),
        )
    )
    await db.flush()

    # 组织额度扣减 + 台账（有成本且归属组织时）
    if org_id is not None and cost_usd:
        await apply_credit(db, org_id, -cost_usd, type="usage", ref=str(record.id), commit=False)

    await db.commit()

    # Prometheus 指标（不影响主流程）
    from app.services import metrics
    metrics.observe(
        model=model, provider=provider, status=status, cached=cached,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cost_usd=cost_usd, duration_ms=duration_ms,
    )
