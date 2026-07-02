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
    import time
    import litellm
    from app.models import ModelCatalog, Provider
    from app.services.router import _resolve_env_credential

    ch = await db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not ch.models:
        raise HTTPException(status_code=400, detail="Channel serves no models")

    model_id = ch.models[0]
    row = (
        await db.execute(
            select(ModelCatalog, Provider)
            .join(Provider, Provider.id == ModelCatalog.provider_id)
            .where(ModelCatalog.model_id == model_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Model {model_id} not in catalog")
    catalog, provider = row
    upstream = (ch.model_map or {}).get(model_id) or catalog.litellm_model
    api_key = ch.api_key or _resolve_env_credential(provider.credential_env)
    api_base = ch.api_base or provider.api_base

    start = time.time()
    ok, error = True, None
    try:
        kwargs = {"model": upstream, "timeout": 30}
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base
        if catalog.mode == "embedding":
            await litellm.aembedding(input="ping", **kwargs)
        else:
            await litellm.acompletion(messages=[{"role": "user", "content": "ping"}], max_tokens=1, **kwargs)
    except Exception as e:
        ok, error = False, str(e)[:300]

    ch.status = "active" if ok else "error"
    await db.commit()
    return {"ok": ok, "latency_ms": int((time.time() - start) * 1000), "model": model_id, "error": error}
