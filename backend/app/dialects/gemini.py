"""Gemini (Google AI) 方言 ↔ 内部 OpenAI 规范互转（P3）。

覆盖：contents/parts 文本、systemInstruction、generationConfig（maxOutputTokens/temperature/topP/stopSequences）、
流式（SSE，alt=sse 风格）、usageMetadata。
未覆盖（后续期）：inline_data 多模态、functionCall（尽力降级为文本）。
"""
import json
from typing import AsyncGenerator


def _text_from_parts(parts) -> str:
    if not isinstance(parts, list):
        return ""
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


# Gemini role: "user" / "model"；OpenAI: "user" / "assistant"
_ROLE_G2O = {"user": "user", "model": "assistant"}


def gemini_to_openai(body: dict, model_id: str) -> dict:
    """Gemini generateContent 请求 → OpenAI chat body"""
    messages = []
    sys_inst = body.get("systemInstruction") or body.get("system_instruction")
    if sys_inst:
        messages.append({"role": "system", "content": _text_from_parts(sys_inst.get("parts", []))})
    for c in body.get("contents", []):
        messages.append({
            "role": _ROLE_G2O.get(c.get("role", "user"), "user"),
            "content": _text_from_parts(c.get("parts", [])),
        })

    out = {"model": model_id, "messages": messages}
    cfg = body.get("generationConfig") or body.get("generation_config") or {}
    if cfg.get("maxOutputTokens") is not None:
        out["max_tokens"] = cfg["maxOutputTokens"]
    if cfg.get("temperature") is not None:
        out["temperature"] = cfg["temperature"]
    if cfg.get("topP") is not None:
        out["top_p"] = cfg["topP"]
    if cfg.get("stopSequences"):
        out["stop"] = cfg["stopSequences"]
    return out


_FINISH_MAP = {"stop": "STOP", "length": "MAX_TOKENS", "content_filter": "SAFETY", "tool_calls": "STOP"}


def _usage_metadata(usage: dict) -> dict:
    return {
        "promptTokenCount": usage.get("prompt_tokens", 0),
        "candidatesTokenCount": usage.get("completion_tokens", 0),
        "totalTokenCount": usage.get("total_tokens", 0),
    }


def openai_to_gemini(data: dict, model_id: str) -> dict:
    """OpenAI 非流式响应 → Gemini generateContent 响应"""
    choice = (data.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    return {
        "candidates": [{
            "content": {"role": "model", "parts": [{"text": text}]},
            "finishReason": _FINISH_MAP.get(choice.get("finish_reason"), "STOP"),
            "index": 0,
        }],
        "usageMetadata": _usage_metadata(data.get("usage") or {}),
        "modelVersion": model_id,
    }


def _gemini_chunk(text: str, model_id: str, finish: str | None = None, usage: dict | None = None) -> dict:
    cand = {"content": {"role": "model", "parts": [{"text": text}]}, "index": 0}
    if finish:
        cand["finishReason"] = finish
    out = {"candidates": [cand], "modelVersion": model_id}
    if usage is not None:
        out["usageMetadata"] = _usage_metadata(usage)
    return out


async def openai_chunks_to_gemini_sse(
    chunks: AsyncGenerator[dict, None], model_id: str
) -> AsyncGenerator[bytes, None]:
    """OpenAI 流式 chunk → Gemini SSE（alt=sse 风格：每行 data: {...}）"""
    last_usage = {}
    finish = None
    try:
        async for data in chunks:
            usage = data.get("usage")
            if usage:
                last_usage = usage
            choice = (data.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if choice.get("finish_reason"):
                finish = _FINISH_MAP.get(choice["finish_reason"], "STOP")
            if piece:
                chunk = _gemini_chunk(piece, model_id)
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
    except Exception as e:
        err = {"error": {"code": 502, "message": str(e), "status": "UNAVAILABLE"}}
        yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n".encode()
        return

    # 收尾块带 finishReason + usageMetadata
    final = _gemini_chunk("", model_id, finish=finish or "STOP", usage=last_usage)
    yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n".encode()
