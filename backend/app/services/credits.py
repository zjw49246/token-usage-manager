"""组织额度（credits）服务：充值 / 赠送 / 消费扣减，均原子更新余额并写台账。

余额存在 organizations.credit_balance_usd，流水存 credit_transactions。
所有变更走 apply_credit：一条带条件/无条件的原子 UPDATE + 一条台账记录。
"""
from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization, CreditTransaction


async def apply_credit(
    db: AsyncSession,
    org_id: int,
    amount_usd: float,
    type: str,
    ref: str | None = None,
    commit: bool = True,
) -> float:
    """原子调整组织余额并写一条台账；返回调整后的余额。

    amount_usd > 0 充值/赠送；< 0 消费/调整。
    """
    await db.execute(
        update(Organization)
        .where(Organization.id == org_id)
        .values(credit_balance_usd=Organization.credit_balance_usd + amount_usd)
    )
    balance = await db.scalar(
        select(Organization.credit_balance_usd).where(Organization.id == org_id)
    )
    db.add(CreditTransaction(
        org_id=org_id,
        amount_usd=amount_usd,
        type=type,
        ref=ref,
        balance_after=balance if balance is not None else 0.0,
    ))
    if commit:
        await db.commit()
    return balance if balance is not None else 0.0
