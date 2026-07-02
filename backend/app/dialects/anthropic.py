"""Anthropic Messages 方言 ↔ 内部 OpenAI 规范互转（P3）。

覆盖：文本消息、system、max_tokens、temperature/top_p、stop_sequences、流式 SSE 事件、usage。
未覆盖（后续期）：tool_use / 多模态图片块（会尽力降级为文本）。
"""
import json
import time
import uuid
from typing import AsyncGenerator


def _text_from_content(content) -> str:
    """Anthropic content 可能是 str 或 [{type:text,text}, ...]，抽出文本"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


def anthropic_to_openai(body: dict) -> dict:
    """Anthropic Messages 请求 → OpenAI chat body"""
    messages = []
    system = body.get("system")
    if system:
        messages.append({"role": "system", "content": _text_from_content(system)})
    for m in body.get("messages", []):
        messages.append({"role": m.get("role", "user"), "content": _text_from_content(m.get("content", ""))})

    out = {"model": body.get("model"), "messages": messages}
    if body.get("max_tokens") is not None:
        out["max_tokens"] = body["max_tokens"]
    for k in ("temperature", "top_p"):
        if body.get(k) is not None:
            out[k] = body[k]
    if body.get("stop_sequences"):
        out["stop"] = body["stop_sequences"]
    if body.get("stream"):
        out["stream"] = True
    return out


_FINISH_MAP = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use", "content_filter": "end_turn"}


def _msg_id() -> str:
    return "msg_" + uuid.uuid4().hex[:24]


def openai_to_anthropic(data: dict, model_id: str) -> dict:
    """OpenAI 非流式响应 → Anthropic Messages 响应"""
    choice = (data.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    return {
        "id": data.get("id") or _msg_id(),
        "type": "message",
        "role": "assistant",
        "model": model_id,
        "content": [{"type": "text", "text": text}],
        "stop_reason": _FINISH_MAP.get(choice.get("finish_reason"), "end_turn"),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


async def openai_chunks_to_anthropic_sse(
    chunks: AsyncGenerator[dict, None], model_id: str
) -> AsyncGenerator[bytes, None]:
    """OpenAI 流式 chunk → Anthropic SSE 事件序列"""
    msg_id = _msg_id()
    input_tokens = 0
    output_tokens = 0
    stop_reason = "end_turn"
    started = False

    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": model_id,
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })
    yield _sse("content_block_start", {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "text", "text": ""},
    })
    yield b": ping\n\n"

    try:
        async for data in chunks:
            usage = data.get("usage")
            if usage:
                input_tokens = usage.get("prompt_tokens", input_tokens)
                output_tokens = usage.get("completion_tokens", output_tokens)
            choice = (data.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if piece:
                started = True
                yield _sse("content_block_delta", {
                    "type": "content_block_delta", "index": 0,
                    "delta": {"type": "text_delta", "text": piece},
                })
            if choice.get("finish_reason"):
                stop_reason = _FINISH_MAP.get(choice["finish_reason"], "end_turn")
    except Exception as e:
        yield _sse("error", {"type": "error", "error": {"type": "api_error", "message": str(e)}})

    yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": output_tokens},
    })
    yield _sse("message_stop", {"type": "message_stop"})
