"""P3 回归测试：Anthropic /v1/messages 与 Gemini /v1beta 入口（含流式）+ 成本记账"""
import asyncio
import json

import pytest
from sqlalchemy import select

from tests.conftest import TestSessionLocal


class _FakeResponse:
    def __init__(self, data): self._data = data
    def model_dump(self, exclude_none=True): return dict(self._data)


def _openai_completion(text="hello", pt=10, ct=20):
    return {
        "id": "chatcmpl-x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct},
    }


def _openai_chunks():
    return [
        {"id": "c", "object": "chat.completion.chunk", "model": "gemini/gemini-2.0-flash",
         "choices": [{"index": 0, "delta": {"content": "he"}}]},
        {"id": "c", "object": "chat.completion.chunk", "model": "gemini/gemini-2.0-flash",
         "choices": [{"index": 0, "delta": {"content": "llo"}, "finish_reason": "stop"}]},
        {"id": "c", "object": "chat.completion.chunk", "model": "gemini/gemini-2.0-flash",
         "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}},
    ]


async def _drain():
    await asyncio.sleep(0.05)


def _patch_nonstream(monkeypatch, captured):
    from app.services import router as core

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(_openai_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)


def _patch_stream(monkeypatch):
    from app.services import router as core

    async def fake_acompletion(**kwargs):
        async def gen():
            for c in _openai_chunks():
                yield _FakeResponse(c)
        return gen()
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)


# ── Anthropic ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_anthropic_nonstream(admin_client, client, monkeypatch):
    captured = {}
    _patch_nonstream(monkeypatch, captured)
    key = (await admin_client.post("/admin/keys", json={"name": "a"})).json()["key"]

    resp = await client.post("/v1/messages", headers={"x-api-key": key}, json={
        "model": "gemini-2.0-flash", "max_tokens": 100, "system": "be brief",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    # Anthropic 响应形状
    assert body["type"] == "message"
    assert body["role"] == "assistant"
    assert body["content"][0]["text"] == "hello"
    assert body["stop_reason"] == "end_turn"
    assert body["usage"] == {"input_tokens": 10, "output_tokens": 20}
    # system 被翻译进 OpenAI messages
    assert captured["messages"][0] == {"role": "system", "content": "be brief"}
    assert captured["max_tokens"] == 100

    await _drain()
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.cost_usd == pytest.approx(10 / 1e6 * 0.1 + 20 / 1e6 * 0.4)


@pytest.mark.asyncio
async def test_anthropic_stream_events(admin_client, client, monkeypatch):
    _patch_stream(monkeypatch)
    key = (await admin_client.post("/admin/keys", json={"name": "a"})).json()["key"]

    resp = await client.post("/v1/messages", headers={"Authorization": f"Bearer {key}"}, json={
        "model": "gemini-2.0-flash", "max_tokens": 50, "stream": True,
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert resp.status_code == 200
    text = resp.text
    assert "event: message_start" in text
    assert "event: content_block_delta" in text
    assert "event: message_stop" in text
    # 文本增量拼起来
    deltas = [json.loads(l[6:])["delta"]["text"]
              for l in text.splitlines() if l.startswith("data: ") and '"text_delta"' in l]
    assert "".join(deltas) == "hello"

    await _drain()
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.total_tokens == 30


# ── Gemini ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gemini_nonstream(admin_client, client, monkeypatch):
    captured = {}
    _patch_nonstream(monkeypatch, captured)
    key = (await admin_client.post("/admin/keys", json={"name": "g"})).json()["key"]

    resp = await client.post(
        f"/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
        json={
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "systemInstruction": {"parts": [{"text": "be brief"}]},
            "generationConfig": {"maxOutputTokens": 100, "temperature": 0.5},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["candidates"][0]["content"]["parts"][0]["text"] == "hello"
    assert body["candidates"][0]["finishReason"] == "STOP"
    assert body["usageMetadata"]["totalTokenCount"] == 30
    # systemInstruction + generationConfig 翻译
    assert captured["messages"][0] == {"role": "system", "content": "be brief"}
    assert captured["max_tokens"] == 100
    assert captured["temperature"] == 0.5


@pytest.mark.asyncio
async def test_gemini_stream(admin_client, client, monkeypatch):
    _patch_stream(monkeypatch)
    key = (await admin_client.post("/admin/keys", json={"name": "g"})).json()["key"]

    resp = await client.post(
        "/v1beta/models/gemini-2.0-flash:streamGenerateContent",
        headers={"x-goog-api-key": key},
        json={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
    )
    assert resp.status_code == 200
    lines = [l for l in resp.text.splitlines() if l.startswith("data: ")]
    texts = []
    finish = None
    for l in lines:
        obj = json.loads(l[6:])
        cand = obj["candidates"][0]
        texts.append(cand["content"]["parts"][0]["text"])
        if cand.get("finishReason"):
            finish = cand["finishReason"]
    assert "".join(texts) == "hello"
    assert finish == "STOP"
    # 尾块带 usageMetadata
    assert json.loads(lines[-1][6:])["usageMetadata"]["totalTokenCount"] == 30


@pytest.mark.asyncio
async def test_ingress_unknown_model_404(admin_client, client, monkeypatch):
    key = (await admin_client.post("/admin/keys", json={"name": "u"})).json()["key"]
    r = await client.post("/v1/messages", headers={"x-api-key": key}, json={
        "model": "no-such", "max_tokens": 10, "messages": [{"role": "user", "content": "x"}],
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_ingress_missing_key_401(client):
    r = await client.post("/v1/messages", json={
        "model": "gemini-2.0-flash", "max_tokens": 10, "messages": [{"role": "user", "content": "x"}],
    })
    assert r.status_code == 401
