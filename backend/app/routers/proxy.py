"""代理入口（OpenAI 方言）：
- GET /v1/models       — 从模型目录返回（带价格/上下文窗口等扩展字段）
- POST /v1/chat/completions — 经 LiteLLM 内核路由到上游

模型不再硬编码：全部来自 model_catalog（见 scripts/seed.py）。
"""
import json
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_api_key
from app.models import ApiKey, ModelCatalog, Provider
from app.services.quota import check_quota
from app.services import router as model_router

router = APIRouter(prefix="/v1", tags=["proxy"])


@router.get("/models")
async def list_models(
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """返回当前 Key 可用的模型列表（OpenAI 格式 + 价格扩展字段）"""
    stmt = (
        select(ModelCatalog, Provider)
        .join(Provider, Provider.id == ModelCatalog.provider_id)
        .where(ModelCatalog.enabled.is_(True), Provider.enabled.is_(True))
        .order_by(Provider.name, ModelCatalog.model_id)
    )
    rows = (await db.execute(stmt)).all()

    allowed = set(api_key.allowed_models) if api_key.allowed_models else None
    data = []
    for m, p in rows:
        if allowed is not None and m.model_id not in allowed:
            continue
        data.append({
            "id": m.model_id,
            "object": "model",
            "owned_by": p.name,
            # ── TokenRouter 扩展字段 ──
            "display_name": m.display_name,
            "context_window": m.context_window,
            "max_output_tokens": m.max_output_tokens,
            "input_price_per_1m": m.input_price_per_1m,
            "output_price_per_1m": m.output_price_per_1m,
            "capabilities": m.capabilities,
            "verified": m.verified,
        })
    return {"object": "list", "data": data}


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    if not api_key.is_active:
        raise HTTPException(status_code=403, detail="API key is disabled")

    try:
        body = json.loads(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Missing 'model' in request body")

    # 目录解析（未知/停用模型 404）→ 配额（含原子预扣）→ LiteLLM 路由（多通道故障转移）
    routes = await model_router.resolve_routes(db, model)
    await check_quota(db, api_key, model)
    return await model_router.route_chat_completion(api_key, routes, body)


@router.post("/embeddings")
async def embeddings(
    request: Request,
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    if not api_key.is_active:
        raise HTTPException(status_code=403, detail="API key is disabled")
    try:
        body = json.loads(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Missing 'model' in request body")
    routes = await model_router.resolve_routes(db, model)
    await check_quota(db, api_key, model)
    return await model_router.route_embeddings(api_key, routes, body)


async def _prepare(request: Request, api_key: ApiKey, db: AsyncSession):
    """公共前置：校验 + 解析 body + 目录解析 + 配额（返回 routes, body）"""
    if not api_key.is_active:
        raise HTTPException(status_code=403, detail="API key is disabled")
    try:
        body = json.loads(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Missing 'model' in request body")
    routes = await model_router.resolve_routes(db, model)
    await check_quota(db, api_key, model)
    return routes, body


@router.post("/rerank")
async def rerank(
    request: Request,
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    routes, body = await _prepare(request, api_key, db)
    return await model_router.route_rerank(api_key, routes, body)


@router.post("/responses")
async def responses(
    request: Request,
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    routes, body = await _prepare(request, api_key, db)
    return await model_router.route_responses(api_key, routes, body)


@router.post("/images/generations")
async def images_generations(
    request: Request,
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    if not api_key.is_active:
        raise HTTPException(status_code=403, detail="API key is disabled")
    try:
        body = json.loads(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Missing 'model' in request body")
    routes = await model_router.resolve_routes(db, model)
    await check_quota(db, api_key, model)
    return await model_router.route_image_generation(api_key, routes, body)
