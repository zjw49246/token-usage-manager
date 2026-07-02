"""模型别名管理（P22，平台超管）：alias → 真实 model_id。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.dependencies import require_superadmin
from app.models import ModelAlias, ModelCatalog

router = APIRouter(prefix="/aliases", tags=["aliases"], dependencies=[Depends(require_superadmin)])


class AliasIn(BaseModel):
    alias: str = Field(..., min_length=1, max_length=150)
    target_model_id: str = Field(..., min_length=1, max_length=150)


@router.get("")
async def list_aliases(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ModelAlias).order_by(ModelAlias.alias))).scalars().all()
    return [{"id": a.id, "alias": a.alias, "target_model_id": a.target_model_id} for a in rows]


@router.post("", status_code=201)
async def create_alias(body: AliasIn, db: AsyncSession = Depends(get_db)):
    target = await db.scalar(select(ModelCatalog.model_id).where(ModelCatalog.model_id == body.target_model_id))
    if target is None:
        raise HTTPException(status_code=404, detail="Target model not in catalog")
    if await db.scalar(select(ModelAlias).where(ModelAlias.alias == body.alias)):
        raise HTTPException(status_code=409, detail="Alias already exists")
    a = ModelAlias(alias=body.alias, target_model_id=body.target_model_id)
    db.add(a)
    await db.commit()
    return {"alias": a.alias, "target_model_id": a.target_model_id}


@router.delete("/{alias}", status_code=204)
async def delete_alias(alias: str, db: AsyncSession = Depends(get_db)):
    a = (await db.execute(select(ModelAlias).where(ModelAlias.alias == alias))).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="Alias not found")
    await db.delete(a)
    await db.commit()
