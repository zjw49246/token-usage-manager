"""Anthropic Messages 入口：POST /v1/messages
让 Anthropic SDK / Claude 客户端不改代码指过来，经内部 OpenAI 规范路由到任意上游。
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
from app.dialects import anthropic as dialect

router = APIRouter(prefix="/v1", tags=["ingress:anthropic"])


@router.post("/messages")
async def anthropic_messages(
    request: Request,
    api_key: ApiKey = Depends(get_api_key_flexible),
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
        raise HTTPException(status_code=400, detail="Missing 'model'")

    route = await core.resolve_model(db, model)
    await check_quota(db, api_key, model)

    openai_body = dialect.anthropic_to_openai(body)

    if body.get("stream"):
        chunks = core.aiter_openai_chunks(api_key, route, openai_body)
        return StreamingResponse(
            dialect.openai_chunks_to_anthropic_sse(chunks, model),
            media_type="text/event-stream",
        )

    data = await core.acompletion_once(api_key, route, openai_body)
    return JSONResponse(content=dialect.openai_to_anthropic(data, model))
