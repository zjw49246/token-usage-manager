"""
代理转发服务：
- 将客户端请求转发到上游 API（Gemini / DeepSeek）
- 根据模型名自动路由到对应的上游服务
- 支持 OpenAI 兼容模式（API Key）和 Vertex AI 模式（Service Account）
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

# DeepSeek 模型前缀
DEEPSEEK_MODEL_PREFIXES = ("deepseek-",)


def _is_deepseek_model(model: str) -> bool:
    """判断是否为 DeepSeek 模型"""
    return any(model.startswith(p) for p in DEEPSEEK_MODEL_PREFIXES)


def _map_model_for_upstream(model: str) -> str:
    """Vertex 模式下将短名转为 google/{model} 格式；其他模式原样返回"""
    if _is_deepseek_model(model):
        return model
    if settings.gemini_use_openai_mode:
        return model
    # Vertex AI 要求 publisher/model 格式，统一加 google/ 前缀
    if not model.startswith("google/"):
        return f"google/{model}"
    return model


def _get_vertex_access_token() -> str:
    """通过 Service Account 获取 Vertex AI OAuth2 Access Token"""
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request as GoogleAuthRequest

    credentials = service_account.Credentials.from_service_account_file(
        settings.google_application_credentials,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    credentials.refresh(GoogleAuthRequest())
    return credentials.token


def _upstream_headers(model: str) -> dict[str, str]:
    """构造上游请求头（含真实凭证），根据模型选择对应的凭证"""
    if _is_deepseek_model(model):
        token = settings.deepseek_api_key
    elif settings.gemini_use_openai_mode:
        token = settings.gemini_api_key
    else:
        token = _get_vertex_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _upstream_url(path: str, model: str) -> str:
    """根据模型选择对应的上游 URL"""
    if _is_deepseek_model(model):
        base = settings.deepseek_base_url.rstrip("/")
    elif settings.gemini_use_openai_mode:
        base = settings.gemini_openai_base_url.rstrip("/")
    else:
        project = settings.gcp_project_id
        location = settings.gcp_location
        base = (
            f"https://aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{location}/endpoints/openapi"
        )
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

    # 自动将短名映射为上游全名（Vertex 模式）
    if body_json.get("model"):
        upstream_model = _map_model_for_upstream(body_json["model"])
        if upstream_model != body_json["model"]:
            body_json["model"] = upstream_model
            body_bytes = json.dumps(body_json).encode()

    upstream_url = _upstream_url(path, model)
    headers = _upstream_headers(model)
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
