"""LiteLLM 路由内核（P1）：替代旧版 services/proxy.py 的硬编码 if/else。

数据驱动路由：model_id → model_catalog → (litellm_model, provider.api_base, 凭证)
- 非流式与流式（OpenAI SSE 格式回吐）
- 按目录单价核算 cost_usd，响应后后台记账
- LiteLLM 异常按上游 status_code 映射回客户端
"""
import asyncio
import json
import os
import random
import time
from typing import AsyncGenerator

import litellm
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import ModelCatalog, Provider, ApiKey, Channel, ModelAlias
from app.services.quota import record_usage
from app.services.cache import cache_key, get_cache

# LiteLLM 全局行为：不落盘、不打调用日志
litellm.drop_params = True  # 上游不认识的参数自动丢弃而不是报错

# 凭证 env 名 → settings 字段的回退映射（.env 由 pydantic 读，不一定进 os.environ）
_SETTINGS_CREDENTIAL_FALLBACK = {
    "GEMINI_API_KEY": lambda: settings.gemini_api_key,
    "DEEPSEEK_API_KEY": lambda: settings.deepseek_api_key,
}


class ModelRoute:
    """一次调用的已解析路由（目录行用于计价/公开名 + 上游调用参数 + 通道标识）"""

    def __init__(self, catalog: ModelCatalog, provider_name: str, upstream_model: str,
                 api_key: str | None, api_base: str | None, channel_id: int | None = None):
        self.catalog = catalog
        self.provider_name = provider_name
        self.upstream_model = upstream_model
        self.api_key = api_key
        self.api_base = api_base
        self.channel_id = channel_id


def _resolve_env_credential(env_name: str | None) -> str | None:
    if not env_name:
        return None
    value = os.environ.get(env_name)
    if not value:
        fallback = _SETTINGS_CREDENTIAL_FALLBACK.get(env_name)
        value = fallback() if fallback else None
    return value or None


def _model_not_found(model_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": {
            "message": f"The model '{model_id}' does not exist or is disabled",
            "type": "invalid_request_error", "code": "model_not_found",
        }},
    )


def _weighted_order(channels: list[Channel]) -> list[Channel]:
    """按 priority 分层（高者先），层内按 weight 加权随机排序，输出故障转移尝试顺序"""
    ordered: list[Channel] = []
    by_prio: dict[int, list[Channel]] = {}
    for ch in channels:
        by_prio.setdefault(ch.priority, []).append(ch)
    for prio in sorted(by_prio, reverse=True):
        tier = by_prio[prio][:]
        # 加权随机洗牌：按 weight 无放回抽样
        while tier:
            weights = [max(1, c.weight) for c in tier]
            pick = random.choices(range(len(tier)), weights=weights, k=1)[0]
            ordered.append(tier.pop(pick))
    return ordered


async def resolve_routes(db: AsyncSession, model_id: str) -> list[ModelRoute]:
    """model_id → 有序的候选路由列表（用于负载均衡 + 故障转移）。

    优先用 channels 表里服务该模型的启用通道（加权随机+优先级排序）；
    若无通道配置，则回退到 model_catalog + provider 的单路由（向后兼容）。
    未知/停用模型 → 404。
    """
    # 模型别名透明改写
    alias_target = await db.scalar(
        select(ModelAlias.target_model_id).where(ModelAlias.alias == model_id)
    )
    if alias_target:
        model_id = alias_target

    row = (
        await db.execute(
            select(ModelCatalog, Provider)
            .join(Provider, Provider.id == ModelCatalog.provider_id)
            .where(ModelCatalog.model_id == model_id)
        )
    ).first()
    if row is None or not row.ModelCatalog.enabled or not row.Provider.enabled:
        raise _model_not_found(model_id)
    catalog, provider = row.ModelCatalog, row.Provider

    # 找服务该模型的启用通道
    all_channels = (
        await db.execute(select(Channel).where(Channel.enabled.is_(True)))
    ).scalars().all()
    serving = [c for c in all_channels if c.models and model_id in c.models]

    if serving:
        # 需要各通道的 provider 前缀/api_base
        prov_by_id = {
            p.id: p for p in (await db.execute(select(Provider))).scalars().all()
        }
        routes: list[ModelRoute] = []
        for ch in _weighted_order(serving):
            prov = prov_by_id.get(ch.provider_id)
            if prov is None or not prov.enabled:
                continue
            upstream = (ch.model_map or {}).get(model_id) or catalog.litellm_model
            api_key = ch.api_key or _resolve_env_credential(prov.credential_env)
            api_base = ch.api_base or prov.api_base
            routes.append(ModelRoute(catalog, prov.name, upstream, api_key, api_base, ch.id))
        if routes:
            return routes

    # 回退：单路由（无通道配置时的行为，与 P1~P5 一致）
    return [ModelRoute(
        catalog, provider.name, catalog.litellm_model,
        _resolve_env_credential(provider.credential_env), provider.api_base,
    )]


async def resolve_model(db: AsyncSession, model_id: str) -> ModelRoute:
    """兼容旧签名：返回首选路由（仅用于存在性校验）"""
    return (await resolve_routes(db, model_id))[0]


def compute_cost(
    catalog: ModelCatalog, input_tokens: int | None, output_tokens: int | None,
    cached_tokens: int | None = 0,
) -> float | None:
    """按目录单价核算成本（USD）。上游 prompt 缓存读的 token 按折扣计价。无价格信息时返回 None。"""
    if catalog.input_price_per_1m is None and catalog.output_price_per_1m is None:
        return None
    cost = 0.0
    in_price = catalog.input_price_per_1m
    if input_tokens and in_price:
        cached = min(cached_tokens or 0, input_tokens)
        billable = input_tokens - cached
        cost += billable / 1_000_000 * in_price
        cost += cached / 1_000_000 * in_price * settings.cache_read_price_ratio
    if output_tokens and catalog.output_price_per_1m:
        cost += output_tokens / 1_000_000 * catalog.output_price_per_1m
    return round(cost, 8)


def _cached_tokens(usage: dict) -> int:
    """从 usage 提取上游 prompt 缓存读 token（OpenAI/Anthropic 经 litellm 归一到 prompt_tokens_details）"""
    d = usage.get("prompt_tokens_details") or {}
    return d.get("cached_tokens") or 0


async def _save_usage_bg(
    api_key: ApiKey,
    route: ModelRoute,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    duration_ms: int,
    status: str = "success",
    error_message: str | None = None,
    cached: bool = False,
    cost_override: float | None = None,
    cached_tokens: int | None = 0,
) -> None:
    """后台异步记账（明细 + token/cost 原子累加），不阻塞响应。

    缓存命中时按 cache_hit_cost_multiplier 折算成本（默认 0=免费）。
    cost_override 用于非 token 计价（如图像按张）；cached_tokens 为上游 prompt 缓存读 token。
    """
    if cost_override is not None:
        cost = cost_override
    else:
        cost = compute_cost(route.catalog, input_tokens, output_tokens, cached_tokens)
    if cached and cost is not None:
        cost = round(cost * settings.cache_hit_cost_multiplier, 8)
    async with AsyncSessionLocal() as db:
        await record_usage(
            db, api_key.id, route.catalog.model_id,
            input_tokens, output_tokens, total_tokens,
            duration_ms, status, error_message,
            provider="cache" if cached else route.provider_name,
            cost_usd=cost,
            org_id=api_key.org_id,
            cached=cached,
            cached_tokens=cached_tokens or None,
        )


def _completion_kwargs(route: ModelRoute, body: dict) -> dict:
    """把客户端请求体转成 litellm.acompletion 参数"""
    kwargs = {k: v for k, v in body.items() if k not in ("model", "stream")}
    kwargs["model"] = route.upstream_model
    if route.api_key:
        kwargs["api_key"] = route.api_key
    if route.api_base:
        kwargs["api_base"] = route.api_base
    kwargs["timeout"] = settings.upstream_timeout
    return kwargs


async def _mark_channel(channel_id: int | None, ok: bool, status_code: int | None = None) -> None:
    """后台更新通道健康状态；鉴权类错误可按配置自动禁用（P18）。best-effort，带瞬时锁重试。"""
    if not channel_id:
        return
    for attempt in range(4):
        try:
            async with AsyncSessionLocal() as db:
                ch = await db.get(Channel, channel_id)
                if ch is None:
                    return
                ch.status = "active" if ok else "error"
                if not ok and settings.channel_auto_disable and status_code in (401, 403):
                    ch.enabled = False
                await db.commit()
            return
        except Exception:
            await asyncio.sleep(0.02 * (attempt + 1))


def _note(route: ModelRoute, ok: bool, exc: Exception | None = None) -> None:
    if route.channel_id:
        code = getattr(exc, "status_code", None) if exc else None
        asyncio.create_task(_mark_channel(route.channel_id, ok, code))


def _map_litellm_error(e: Exception) -> HTTPException:
    status = getattr(e, "status_code", None) or 502
    message = getattr(e, "message", None) or str(e)
    return HTTPException(status_code=status, detail=f"Upstream error: {message}")


def _as_routes(routes) -> list[ModelRoute]:
    """兼容：既接受单个 ModelRoute 也接受列表"""
    return routes if isinstance(routes, list) else [routes]


def _attempts(routes: list[ModelRoute]) -> list[ModelRoute]:
    """按 max_retries 截断尝试次数（首次 + 若干次故障转移）"""
    return routes[: max(1, min(len(routes), settings.max_retries + 1))]


# ══════════════════ 可复用核心（产出 OpenAI 规范结果 + 记账 + 故障转移）══════════════════
# 三种入口方言（OpenAI / Anthropic / Gemini）都建立在这两个函数之上：
#   acompletion_once  → 非流式，返回 OpenAI 响应 dict
#   aiter_openai_chunks → 流式，逐块 yield OpenAI chunk dict
# 传入有序候选路由（多通道），逐条尝试实现负载均衡 + 失败故障转移。


async def acompletion_once(api_key: ApiKey, routes, body: dict) -> dict:
    """非流式：缓存命中直接返回；否则按候选路由顺序尝试（失败即换下一通道），首个成功即返回并记账"""
    routes = _attempts(_as_routes(routes))
    model_id = routes[0].catalog.model_id
    start_ms = int(time.time() * 1000)

    # 缓存查询（相同请求去重复用）
    ckey = None
    if settings.cache_enabled:
        ckey = cache_key(model_id, body)
        cached_data = await get_cache().get(ckey)
        if cached_data is not None:
            usage = cached_data.get("usage") or {}
            asyncio.create_task(_save_usage_bg(
                api_key, routes[0],
                usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"),
                int(time.time() * 1000) - start_ms, cached=True,
            ))
            return cached_data

    last_exc = None
    for route in routes:
        try:
            resp = await litellm.acompletion(**_completion_kwargs(route, body), stream=False)
        except Exception as e:
            last_exc = e
            _note(route, False, e)
            continue
        _note(route, True)
        duration_ms = int(time.time() * 1000) - start_ms
        data = resp.model_dump(exclude_none=True)
        data["model"] = route.catalog.model_id
        usage = data.get("usage") or {}
        if ckey is not None:
            await get_cache().set(ckey, data, settings.cache_ttl_seconds)
        asyncio.create_task(_save_usage_bg(
            api_key, route,
            usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"),
            duration_ms, cached_tokens=_cached_tokens(usage),
        ))
        return data

    # 全部通道失败
    asyncio.create_task(_save_usage_bg(
        api_key, routes[-1], None, None, None,
        int(time.time() * 1000) - start_ms, "error", str(last_exc)[:500],
    ))
    raise _map_litellm_error(last_exc)


async def aiter_openai_chunks(api_key: ApiKey, routes, body: dict) -> AsyncGenerator[dict, None]:
    """流式：按候选路由尝试建流（建流前失败可换通道），成流后逐块 yield；记账在 finally 统一完成。

    注意：一旦开始产出 chunk 就不再重试（无法回滚已发给客户端的内容）——这是流式故障转移的通行边界。
    """
    routes = _attempts(_as_routes(routes))
    start_ms = int(time.time() * 1000)
    stream = None
    chosen = None
    last_exc = None
    for route in routes:
        try:
            stream = await litellm.acompletion(
                **_completion_kwargs(route, body), stream=True, stream_options={"include_usage": True},
            )
            chosen = route
            break
        except Exception as e:
            last_exc = e
            continue

    if stream is None:
        asyncio.create_task(_save_usage_bg(
            api_key, routes[-1], None, None, None,
            int(time.time() * 1000) - start_ms, "error", str(last_exc)[:500],
        ))
        raise _map_litellm_error(last_exc)

    inp = out = total = None
    cached_tok = 0
    status, error_msg = "success", None
    try:
        async for chunk in stream:
            data = chunk.model_dump(exclude_none=True)
            data["model"] = chosen.catalog.model_id
            usage = data.get("usage")
            if usage:
                inp = usage.get("prompt_tokens", inp)
                out = usage.get("completion_tokens", out)
                total = usage.get("total_tokens", total)
                cached_tok = _cached_tokens(usage) or cached_tok
            yield data
    except Exception as e:
        status, error_msg = "error", str(e)[:500]
        raise
    finally:
        duration_ms = int(time.time() * 1000) - start_ms
        asyncio.create_task(_save_usage_bg(
            api_key, chosen, inp, out, total, duration_ms, status, error_msg,
            cached_tokens=cached_tok,
        ))


# ══════════════════ OpenAI 入口格式化 ══════════════════


async def _openai_sse(api_key: ApiKey, routes, body: dict) -> AsyncGenerator[bytes, None]:
    try:
        async for data in aiter_openai_chunks(api_key, routes, body):
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
        yield b"data: [DONE]\n\n"
    except Exception as e:
        err = {"error": {"message": str(e), "type": "upstream_error"}}
        yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n".encode()


async def route_chat_completion(
    api_key: ApiKey, routes, body: dict
) -> StreamingResponse | JSONResponse:
    """OpenAI chat/completions 入口（流式/非流式）"""
    if bool(body.get("stream", False)):
        return StreamingResponse(
            _openai_sse(api_key, routes, body),
            media_type="text/event-stream",
        )
    return JSONResponse(content=await acompletion_once(api_key, routes, body))


# ══════════════════ Embeddings / Images 端点（P8）══════════════════


async def _try_failover(api_key: ApiKey, routes, fn, extract_usage, extract_cost):
    """通用故障转移执行器：逐条通道试 fn(kwargs)，成功即记账返回 data；全失败记 error 抛出。

    fn(route) -> (data_dict, resp)；extract_usage(data)->(inp,out,total)；extract_cost(route,data)->cost
    """
    routes = _attempts(_as_routes(routes))
    start_ms = int(time.time() * 1000)
    last_exc = None
    for route in routes:
        try:
            data = await fn(route)
        except Exception as e:
            last_exc = e
            continue
        duration_ms = int(time.time() * 1000) - start_ms
        inp, out, total = extract_usage(data)
        asyncio.create_task(_save_usage_bg(
            api_key, route, inp, out, total, duration_ms,
            cost_override=extract_cost(route, data),
        ))
        return data
    asyncio.create_task(_save_usage_bg(
        api_key, routes[-1], None, None, None,
        int(time.time() * 1000) - start_ms, "error", str(last_exc)[:500],
    ))
    raise _map_litellm_error(last_exc)


async def route_embeddings(api_key: ApiKey, routes, body: dict) -> JSONResponse:
    """OpenAI /v1/embeddings（token 计价，走目录单价）"""
    async def call(route: ModelRoute):
        kwargs = {k: v for k, v in body.items() if k != "model"}
        kwargs["model"] = route.upstream_model
        if route.api_key:
            kwargs["api_key"] = route.api_key
        if route.api_base:
            kwargs["api_base"] = route.api_base
        resp = await litellm.aembedding(**kwargs)
        data = resp.model_dump(exclude_none=True)
        data["model"] = route.catalog.model_id
        return data

    def usage(data):
        u = data.get("usage") or {}
        return u.get("prompt_tokens"), 0, u.get("total_tokens")

    def cost(route, data):
        u = data.get("usage") or {}
        return compute_cost(route.catalog, u.get("prompt_tokens"), 0)

    data = await _try_failover(api_key, routes, call, usage, cost)
    return JSONResponse(content=data)


async def _route_litellm_json(api_key: ApiKey, routes, body: dict, litellm_fn, strip=("model",)) -> dict:
    """通用非流式端点执行器（rerank/responses 等）：逐通道故障转移，成本用 litellm.completion_cost 兜底。"""
    routes = _attempts(_as_routes(routes))
    start_ms = int(time.time() * 1000)
    last_exc = None
    for route in routes:
        try:
            kwargs = {k: v for k, v in body.items() if k not in strip}
            kwargs["model"] = route.upstream_model
            if route.api_key:
                kwargs["api_key"] = route.api_key
            if route.api_base:
                kwargs["api_base"] = route.api_base
            resp = await litellm_fn(**kwargs)
        except Exception as e:
            last_exc = e
            _note(route, False, e)
            continue
        _note(route, True)
        duration_ms = int(time.time() * 1000) - start_ms
        data = resp.model_dump(exclude_none=True) if hasattr(resp, "model_dump") else dict(resp)
        data["model"] = route.catalog.model_id
        try:
            cost = litellm.completion_cost(completion_response=resp)
        except Exception:
            cost = None
        u = data.get("usage") or {}
        asyncio.create_task(_save_usage_bg(
            api_key, route,
            u.get("prompt_tokens"), u.get("completion_tokens"), u.get("total_tokens"),
            duration_ms, cost_override=cost,
        ))
        return data
    asyncio.create_task(_save_usage_bg(
        api_key, routes[-1], None, None, None,
        int(time.time() * 1000) - start_ms, "error", str(last_exc)[:500],
    ))
    raise _map_litellm_error(last_exc)


async def route_audio_speech(api_key: ApiKey, routes, body: dict):
    """OpenAI /v1/audio/speech（TTS）：返回音频二进制"""
    from fastapi.responses import Response
    routes = _attempts(_as_routes(routes))
    start_ms = int(time.time() * 1000)
    last_exc = None
    for route in routes:
        try:
            kwargs = {k: v for k, v in body.items() if k != "model"}
            kwargs["model"] = route.upstream_model
            if route.api_key:
                kwargs["api_key"] = route.api_key
            if route.api_base:
                kwargs["api_base"] = route.api_base
            resp = await litellm.aspeech(**kwargs)
        except Exception as e:
            last_exc = e
            continue
        audio = getattr(resp, "content", None)
        if audio is None and hasattr(resp, "read"):
            audio = resp.read()
        try:
            cost = litellm.completion_cost(completion_response=resp)
        except Exception:
            cost = None
        asyncio.create_task(_save_usage_bg(
            api_key, route, None, None, None,
            int(time.time() * 1000) - start_ms, cost_override=cost,
        ))
        fmt = body.get("response_format", "mp3")
        media = {"mp3": "audio/mpeg", "opus": "audio/opus", "aac": "audio/aac",
                 "flac": "audio/flac", "wav": "audio/wav", "pcm": "audio/pcm"}.get(fmt, "audio/mpeg")
        return Response(content=audio or b"", media_type=media)
    asyncio.create_task(_save_usage_bg(
        api_key, routes[-1], None, None, None,
        int(time.time() * 1000) - start_ms, "error", str(last_exc)[:500],
    ))
    raise _map_litellm_error(last_exc)


async def route_audio_transcription(api_key: ApiKey, routes, model_id: str,
                                    file_tuple: tuple, extra: dict) -> JSONResponse:
    """OpenAI /v1/audio/transcriptions（STT）：上传音频返回文本"""
    routes = _attempts(_as_routes(routes))
    start_ms = int(time.time() * 1000)
    last_exc = None
    for route in routes:
        try:
            kwargs = dict(extra)
            kwargs["model"] = route.upstream_model
            kwargs["file"] = file_tuple
            if route.api_key:
                kwargs["api_key"] = route.api_key
            if route.api_base:
                kwargs["api_base"] = route.api_base
            resp = await litellm.atranscription(**kwargs)
        except Exception as e:
            last_exc = e
            continue
        data = resp.model_dump(exclude_none=True) if hasattr(resp, "model_dump") else {"text": getattr(resp, "text", "")}
        try:
            cost = litellm.completion_cost(completion_response=resp)
        except Exception:
            cost = None
        asyncio.create_task(_save_usage_bg(
            api_key, route, None, None, None,
            int(time.time() * 1000) - start_ms, cost_override=cost,
        ))
        return JSONResponse(content=data)
    asyncio.create_task(_save_usage_bg(
        api_key, routes[-1], None, None, None,
        int(time.time() * 1000) - start_ms, "error", str(last_exc)[:500],
    ))
    raise _map_litellm_error(last_exc)


async def route_rerank(api_key: ApiKey, routes, body: dict) -> JSONResponse:
    """OpenAI/Cohere 风格 /v1/rerank"""
    data = await _route_litellm_json(api_key, routes, body, litellm.arerank)
    return JSONResponse(content=data)


async def route_responses(api_key: ApiKey, routes, body: dict) -> JSONResponse:
    """OpenAI Responses API /v1/responses（非流式）"""
    data = await _route_litellm_json(api_key, routes, body, litellm.aresponses)
    return JSONResponse(content=data)


async def route_video_generation(api_key: ApiKey, routes, body: dict) -> JSONResponse:
    """视频生成 /v1/videos/generations（litellm.avideo_generation）"""
    data = await _route_litellm_json(api_key, routes, body, litellm.avideo_generation)
    return JSONResponse(content=data)


async def route_image_generation(api_key: ApiKey, routes, body: dict) -> JSONResponse:
    """OpenAI /v1/images/generations（按张计价）"""
    n = int(body.get("n", 1) or 1)

    async def call(route: ModelRoute):
        kwargs = {k: v for k, v in body.items() if k != "model"}
        kwargs["model"] = route.upstream_model
        if route.api_key:
            kwargs["api_key"] = route.api_key
        if route.api_base:
            kwargs["api_base"] = route.api_base
        resp = await litellm.aimage_generation(**kwargs)
        return resp.model_dump(exclude_none=True)

    def usage(data):
        return None, None, None

    def cost(route, data):
        price = route.catalog.image_price
        imgs = len(data.get("data") or []) or n
        return round(price * imgs, 8) if price else None

    data = await _try_failover(api_key, routes, call, usage, cost)
    return JSONResponse(content=data)
