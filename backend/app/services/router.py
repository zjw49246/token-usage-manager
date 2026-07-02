"""LiteLLM 路由内核（P1）：替代旧版 services/proxy.py 的硬编码 if/else。

数据驱动路由：model_id → model_catalog → (litellm_model, provider.api_base, 凭证)
- 非流式与流式（OpenAI SSE 格式回吐）
- 按目录单价核算 cost_usd，响应后后台记账
- LiteLLM 异常按上游 status_code 映射回客户端
"""
import asyncio
import json
import os
import time
from typing import AsyncGenerator

import litellm
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import ModelCatalog, Provider, ApiKey
from app.services.quota import record_usage

# LiteLLM 全局行为：不落盘、不打调用日志
litellm.drop_params = True  # 上游不认识的参数自动丢弃而不是报错

# 凭证 env 名 → settings 字段的回退映射（.env 由 pydantic 读，不一定进 os.environ）
_SETTINGS_CREDENTIAL_FALLBACK = {
    "GEMINI_API_KEY": lambda: settings.gemini_api_key,
    "DEEPSEEK_API_KEY": lambda: settings.deepseek_api_key,
}


class ModelRoute:
    """一次调用所需的路由信息（目录行 + 供应商 + 凭证）"""

    def __init__(self, catalog: ModelCatalog, provider: Provider, api_key: str | None):
        self.catalog = catalog
        self.provider = provider
        self.api_key = api_key


def _resolve_credential(provider: Provider) -> str | None:
    env_name = provider.credential_env
    if not env_name:
        return None
    value = os.environ.get(env_name)
    if not value:
        fallback = _SETTINGS_CREDENTIAL_FALLBACK.get(env_name)
        value = fallback() if fallback else None
    return value or None


async def resolve_model(db: AsyncSession, model_id: str) -> ModelRoute:
    """model_id → 路由信息；未知/停用模型返回 OpenAI 风格 404"""
    row = (
        await db.execute(
            select(ModelCatalog, Provider)
            .join(Provider, Provider.id == ModelCatalog.provider_id)
            .where(ModelCatalog.model_id == model_id)
        )
    ).first()
    if row is None or not row.ModelCatalog.enabled or not row.Provider.enabled:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "message": f"The model '{model_id}' does not exist or is disabled",
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                }
            },
        )
    return ModelRoute(row.ModelCatalog, row.Provider, _resolve_credential(row.Provider))


def compute_cost(
    catalog: ModelCatalog, input_tokens: int | None, output_tokens: int | None
) -> float | None:
    """按目录单价核算成本（USD）。无价格信息时返回 None。"""
    if catalog.input_price_per_1m is None and catalog.output_price_per_1m is None:
        return None
    cost = 0.0
    if input_tokens and catalog.input_price_per_1m:
        cost += input_tokens / 1_000_000 * catalog.input_price_per_1m
    if output_tokens and catalog.output_price_per_1m:
        cost += output_tokens / 1_000_000 * catalog.output_price_per_1m
    return round(cost, 8)


async def _save_usage_bg(
    api_key: ApiKey,
    route: ModelRoute,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    duration_ms: int,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    """后台异步记账（明细 + token/cost 原子累加），不阻塞响应"""
    cost = compute_cost(route.catalog, input_tokens, output_tokens)
    async with AsyncSessionLocal() as db:
        await record_usage(
            db, api_key.id, route.catalog.model_id,
            input_tokens, output_tokens, total_tokens,
            duration_ms, status, error_message,
            provider=route.provider.name,
            cost_usd=cost,
            org_id=api_key.org_id,
        )


def _completion_kwargs(route: ModelRoute, body: dict) -> dict:
    """把客户端请求体转成 litellm.acompletion 参数"""
    kwargs = {k: v for k, v in body.items() if k not in ("model", "stream")}
    kwargs["model"] = route.catalog.litellm_model
    if route.api_key:
        kwargs["api_key"] = route.api_key
    if route.provider.api_base:
        kwargs["api_base"] = route.provider.api_base
    kwargs["timeout"] = 600
    return kwargs


def _map_litellm_error(e: Exception) -> HTTPException:
    status = getattr(e, "status_code", None) or 502
    message = getattr(e, "message", None) or str(e)
    return HTTPException(status_code=status, detail=f"Upstream error: {message}")


# ══════════════════ 可复用核心（产出 OpenAI 规范结果 + 记账）══════════════════
# 三种入口方言（OpenAI / Anthropic / Gemini）都建立在这两个函数之上：
#   acompletion_once  → 非流式，返回 OpenAI 响应 dict
#   aiter_openai_chunks → 流式，逐块 yield OpenAI chunk dict
# 记账（token/成本）在核心统一完成，方言层只负责格式转换。


async def acompletion_once(api_key: ApiKey, route: ModelRoute, body: dict) -> dict:
    """非流式：调用 LiteLLM，返回 OpenAI 响应 dict（对外回显公开模型名），并记账"""
    kwargs = _completion_kwargs(route, body)
    start_ms = int(time.time() * 1000)
    try:
        resp = await litellm.acompletion(**kwargs, stream=False)
    except Exception as e:
        asyncio.create_task(_save_usage_bg(
            api_key, route, None, None, None,
            int(time.time() * 1000) - start_ms, "error", str(e)[:500],
        ))
        raise _map_litellm_error(e)

    duration_ms = int(time.time() * 1000) - start_ms
    data = resp.model_dump(exclude_none=True)
    data["model"] = route.catalog.model_id
    usage = data.get("usage") or {}
    asyncio.create_task(_save_usage_bg(
        api_key, route,
        usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"),
        duration_ms,
    ))
    return data


async def aiter_openai_chunks(api_key: ApiKey, route: ModelRoute, body: dict) -> AsyncGenerator[dict, None]:
    """流式：逐块 yield OpenAI chunk dict（尾块含 usage）；异常向上抛，记账在 finally 统一完成"""
    kwargs = _completion_kwargs(route, body)
    start_ms = int(time.time() * 1000)
    inp = out = total = None
    status, error_msg = "success", None
    try:
        stream = await litellm.acompletion(
            **kwargs, stream=True, stream_options={"include_usage": True},
        )
        async for chunk in stream:
            data = chunk.model_dump(exclude_none=True)
            data["model"] = route.catalog.model_id
            usage = data.get("usage")
            if usage:
                inp = usage.get("prompt_tokens", inp)
                out = usage.get("completion_tokens", out)
                total = usage.get("total_tokens", total)
            yield data
    except Exception as e:
        status, error_msg = "error", str(e)[:500]
        raise
    finally:
        duration_ms = int(time.time() * 1000) - start_ms
        asyncio.create_task(_save_usage_bg(
            api_key, route, inp, out, total, duration_ms, status, error_msg,
        ))


# ══════════════════ OpenAI 入口格式化 ══════════════════


async def _openai_sse(api_key: ApiKey, route: ModelRoute, body: dict) -> AsyncGenerator[bytes, None]:
    try:
        async for data in aiter_openai_chunks(api_key, route, body):
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
        yield b"data: [DONE]\n\n"
    except Exception as e:
        err = {"error": {"message": str(e), "type": "upstream_error"}}
        yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n".encode()


async def route_chat_completion(
    api_key: ApiKey, route: ModelRoute, body: dict
) -> StreamingResponse | JSONResponse:
    """OpenAI chat/completions 入口（流式/非流式）"""
    if bool(body.get("stream", False)):
        return StreamingResponse(
            _openai_sse(api_key, route, body),
            media_type="text/event-stream",
        )
    return JSONResponse(content=await acompletion_once(api_key, route, body))
