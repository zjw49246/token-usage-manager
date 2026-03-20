import json
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_api_key
from app.models import ApiKey
from app.services.quota import check_quota
from app.services.proxy import proxy_request
from app.config import settings

router = APIRouter(prefix="/v1", tags=["proxy"])

# 支持的 Gemini 模型列表（可扩展）
GEMINI_MODELS = [
    # Gemini 3 系列
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    # Gemini 2.5 系列（稳定版）
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    # Gemini 2.0 系列（已弃用，保留兼容）
    "gemini-2.0-flash",
]


@router.get("/models")
async def list_models(api_key: ApiKey = Depends(get_current_api_key)):
    """返回当前 Key 可用的模型列表"""
    if api_key.allowed_models:
        models = [m for m in GEMINI_MODELS if m in api_key.allowed_models]
    else:
        models = GEMINI_MODELS
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "owned_by": "google"}
            for m in models
        ],
    }


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    if not api_key.is_active:
        raise HTTPException(status_code=403, detail="API key is disabled")

    # 从请求体提取模型名
    try:
        body = json.loads(await request.body())
        model = body.get("model", "gemini-2.5-flash")
    except Exception:
        model = "gemini-2.5-flash"

    await check_quota(db, api_key, model)

    return await proxy_request(request, "/chat/completions", api_key.id, model)
