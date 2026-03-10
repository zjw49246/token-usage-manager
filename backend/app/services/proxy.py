"""
代理转发服务：
- 将客户端请求转发到上游 Gemini API
- 支持流式（SSE）和非流式两种模式
- 响应结束后异步记录用量
"""
import json
import time
import asyncio
from typing import AsyncGenerator

import httpx
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.quota import record_usage


def _upstream_headers() -> dict[str, str]:
    """构造上游请求头（含真实凭证）"""
    return {
        "Authorization": f"Bearer {settings.gemini_api_key}",
        "Content-Type": "application/json",
    }


def _upstream_url(path: str) -> str:
    base = settings.gemini_openai_base_url.rstrip("/")
    return f"{base}{path}"


def _extract_usage(body: dict) -> tuple[int | None, int | None, int | None]:
    """从响应 JSON 提取 (input_tokens, output_tokens, total_tokens)"""
    usage = body.get("usage", {})
    return (
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        usage.get("total_tokens"),
    )


async def _save_usage_bg(
    api_key_id: int,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    duration_ms: int,
    status: str = "success",
    error_message: str | None = None,
):
    """后台异步写用量，不阻塞响应"""
    async with AsyncSessionLocal() as db:
        await record_usage(
            db, api_key_id, model,
            input_tokens, output_tokens, total_tokens,
            duration_ms, status, error_message,
        )


async def proxy_request(
    request: Request,
    path: str,
    api_key_id: int,
    model: str,
) -> StreamingResponse | JSONResponse:
    """转发请求到上游，处理流式和非流式响应"""
    body_bytes = await request.body()
    is_stream = False
    try:
        body_json = json.loads(body_bytes)
        is_stream = bool(body_json.get("stream", False))
    except Exception:
        body_json = {}

    upstream_url = _upstream_url(path)
    headers = _upstream_headers()
    # 保留客户端传来的其他 headers（去掉 host/authorization）
    for k, v in request.headers.items():
        if k.lower() not in ("host", "authorization", "content-length", "content-type"):
            headers[k] = v

    start_ms = int(time.time() * 1000)

    if is_stream:
        return StreamingResponse(
            _stream_upstream(upstream_url, headers, body_bytes, api_key_id, model, start_ms),
            media_type="text/event-stream",
        )
    else:
        return await _forward_normal(upstream_url, headers, body_bytes, api_key_id, model, start_ms)


async def _forward_normal(
    url: str,
    headers: dict,
    body: bytes,
    api_key_id: int,
    model: str,
    start_ms: int,
) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(url, headers=headers, content=body)
    except httpx.RequestError as e:
        asyncio.create_task(_save_usage_bg(
            api_key_id, model, None, None, None,
            int(time.time() * 1000) - start_ms, "error", str(e),
        ))
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}")

    duration_ms = int(time.time() * 1000) - start_ms

    if resp.status_code >= 400:
        asyncio.create_task(_save_usage_bg(
            api_key_id, model, None, None, None,
            duration_ms, "error", resp.text[:500],
        ))
        return JSONResponse(content=resp.json(), status_code=resp.status_code)

    try:
        resp_json = resp.json()
    except Exception:
        return JSONResponse(content={"error": "Invalid upstream response"}, status_code=502)

    inp, out, total = _extract_usage(resp_json)
    asyncio.create_task(_save_usage_bg(api_key_id, model, inp, out, total, duration_ms))
    return JSONResponse(content=resp_json, status_code=resp.status_code)


async def _stream_upstream(
    url: str,
    headers: dict,
    body: bytes,
    api_key_id: int,
    model: str,
    start_ms: int,
) -> AsyncGenerator[bytes, None]:
    inp, out, total = None, None, None
    status = "success"
    error_msg = None

    try:
        async with httpx.AsyncClient(timeout=600) as client:
            async with client.stream("POST", url, headers=headers, content=body) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk
                    # 尝试从 SSE chunk 提取 usage（最后一个含 usage 的 data 行）
                    try:
                        for line in chunk.decode("utf-8", errors="ignore").splitlines():
                            if line.startswith("data:") and "[DONE]" not in line:
                                data = json.loads(line[5:].strip())
                                if "usage" in data and data["usage"]:
                                    u = data["usage"]
                                    inp = u.get("prompt_tokens", inp)
                                    out = u.get("completion_tokens", out)
                                    total = u.get("total_tokens", total)
                    except Exception:
                        pass
    except Exception as e:
        status = "error"
        error_msg = str(e)

    duration_ms = int(time.time() * 1000) - start_ms
    asyncio.create_task(_save_usage_bg(api_key_id, model, inp, out, total, duration_ms, status, error_msg))
