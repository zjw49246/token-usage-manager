"""Stripe webhook（P9）：支付完成后给组织入账（幂等）。"""
from fastapi import APIRouter, Request, HTTPException, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CreditTransaction
from app.services import payments
from app.services.credits import apply_credit

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if not payments.stripe_enabled():
        raise HTTPException(status_code=400, detail="Stripe not configured")
    payload = await request.body()
    try:
        result = payments.parse_webhook_event(payload, stripe_signature or "")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook: {e}")

    if result is None:
        return {"received": True}  # 非充值完成事件，忽略

    # 幂等：同一支付 ref 只入账一次
    exists = (
        await db.execute(
            select(CreditTransaction).where(
                CreditTransaction.ref == result["ref"], CreditTransaction.type == "topup"
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        await apply_credit(db, result["org_id"], result["amount_usd"], type="topup", ref=result["ref"])
    return {"received": True, "credited": exists is None}
