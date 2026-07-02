"""模型目录（登录用户可读）：供前端选模型 + 模型对比/价格页（P4 复用）"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, ModelCatalog, Provider

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/models")
async def list_catalog_models(
    provider: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """全量模型目录（带价格/上下文窗口/能力），可按供应商过滤"""
    stmt = (
        select(ModelCatalog, Provider)
        .join(Provider, Provider.id == ModelCatalog.provider_id)
        .where(ModelCatalog.enabled.is_(True), Provider.enabled.is_(True))
        .order_by(Provider.name, ModelCatalog.model_id)
    )
    if provider:
        stmt = stmt.where(Provider.name == provider)
    rows = (await db.execute(stmt)).all()
    return {
        "object": "list",
        "data": [
            {
                "id": m.model_id,
                "provider": p.name,
                "display_name": m.display_name,
                "input_price_per_1m": m.input_price_per_1m,
                "output_price_per_1m": m.output_price_per_1m,
                "context_window": m.context_window,
                "max_output_tokens": m.max_output_tokens,
                "capabilities": m.capabilities,
                "verified": m.verified,
            }
            for m, p in rows
        ],
    }
