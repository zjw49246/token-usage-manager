"""Gemini (Google AI) 入口：
- POST /v1beta/models/{model}:generateContent
- POST /v1beta/models/{model}:streamGenerateContent
让 google-genai SDK / Gemini 客户端不改代码指过来（base_url 换成本服务）。
模型名在 path 里（形如 models/gemini-2.5-flash:generateContent）。
"""
import json
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_api_key_flexible
from app.models import ApiKey
from app.services.quota import check_quota
from app.services import router as core
from app.dialects import gemini as dialect

router = APIRouter(prefix="/v1beta", tags=["ingress:gemini"])


async def _handle(model_and_action: str, request: Request, api_key: ApiKey, db: AsyncSession, streaming: bool):
    if not api_key.is_active:
        raise HTTPException(status_code=403, detail="API key is disabled")
    # path 形如 "gemini-2.5-flash"（action 已由路由后缀区分）
    model = model_and_action
    try:
        body = json.loads(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    route = await core.resolve_model(db, model)
    await check_quota(db, api_key, model)

    openai_body = dialect.gemini_to_openai(body, model)

    if streaming:
        chunks = core.aiter_openai_chunks(api_key, route, openai_body)
        return StreamingResponse(
            dialect.openai_chunks_to_gemini_sse(chunks, model),
            media_type="text/event-stream",
        )
    data = await core.acompletion_once(api_key, route, openai_body)
    return JSONResponse(content=dialect.openai_to_gemini(data, model))


@router.post("/models/{model}:generateContent")
async def generate_content(
    model: str, request: Request,
    api_key: ApiKey = Depends(get_api_key_flexible), db: AsyncSession = Depends(get_db),
):
    return await _handle(model, request, api_key, db, streaming=False)


@router.post("/models/{model}:streamGenerateContent")
async def stream_generate_content(
    model: str, request: Request,
    api_key: ApiKey = Depends(get_api_key_flexible), db: AsyncSession = Depends(get_db),
):
    return await _handle(model, request, api_key, db, streaming=True)
