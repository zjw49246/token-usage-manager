"""上游通道管理（P6，平台超管）：负载均衡 + 故障转移的通道 CRUD。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_superadmin
from app.models import Channel, Provider, User
from app.schemas import ChannelCreate, ChannelUpdate, ChannelOut

router = APIRouter(prefix="/channels", tags=["channels"], dependencies=[Depends(require_superadmin)])


def _to_out(ch: Channel) -> ChannelOut:
    out = ChannelOut.model_validate(ch)
    out.has_key = bool(ch.api_key)
    total = (ch.success_count or 0) + (ch.error_count or 0)
    out.success_rate = round(ch.success_count / total, 4) if total else None
    return out


@router.get("/providers")
async def list_providers(db: AsyncSession = Depends(get_db)):
    """供应商列表（建通道时选 provider）"""
    provs = (await db.execute(select(Provider).order_by(Provider.name))).scalars().all()
    return [{"id": p.id, "name": p.name, "litellm_prefix": p.litellm_prefix,
             "api_base": p.api_base, "credential_env": p.credential_env, "enabled": p.enabled}
            for p in provs]


@router.get("", response_model=list[ChannelOut])
async def list_channels(db: AsyncSession = Depends(get_db)):
    chans = (await db.execute(select(Channel).order_by(Channel.priority.desc(), Channel.id))).scalars().all()
    return [_to_out(c) for c in chans]


@router.post("", response_model=ChannelOut, status_code=201)
async def create_channel(body: ChannelCreate, db: AsyncSession = Depends(get_db)):
    if await db.get(Provider, body.provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    ch = Channel(
        name=body.name, provider_id=body.provider_id,
        api_key=body.api_key, api_base=body.api_base,
        models=body.models, model_map=body.model_map,
        weight=body.weight, priority=body.priority, enabled=body.enabled,
    )
    db.add(ch)
    await db.commit()
    await db.refresh(ch)
    return _to_out(ch)


@router.patch("/{channel_id}", response_model=ChannelOut)
async def update_channel(channel_id: int, body: ChannelUpdate, db: AsyncSession = Depends(get_db)):
    ch = await db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(ch, field, val)
    await db.commit()
    await db.refresh(ch)
    return _to_out(ch)


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(channel_id: int, db: AsyncSession = Depends(get_db)):
    ch = await db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    await db.delete(ch)
    await db.commit()


@router.post("/{channel_id}/test")
async def test_channel(channel_id: int, db: AsyncSession = Depends(get_db)):
    """对通道做一次最小连通性测试，更新 status，返回 {ok, latency_ms, model, error}。"""
    from app.services.channel_health import test_channel_conn
    ch = await db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return await test_channel_conn(db, ch)


@router.post("/test-all")
async def test_all(db: AsyncSession = Depends(get_db)):
    """巡检所有启用通道"""
    from app.services.channel_health import test_all_channels
    return {"results": await test_all_channels()}
