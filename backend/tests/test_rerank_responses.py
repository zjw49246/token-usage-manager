"""P15 回归测试：/v1/rerank 与 /v1/responses 端点"""
import asyncio

import pytest
from sqlalchemy import select

from tests.conftest import TestSessionLocal


class _Fake:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


async def _drain():
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_rerank(admin_client, client, monkeypatch):
    from app.services import router as core
    captured = {}

    async def fake_arerank(**kwargs):
        captured.update(kwargs)
        return _Fake({
            "id": "rr", "model": "cohere/rerank-v3.5",
            "results": [{"index": 1, "relevance_score": 0.98}, {"index": 0, "relevance_score": 0.12}],
            "usage": {"prompt_tokens": 50, "total_tokens": 50},
        })
    monkeypatch.setattr(core.litellm, "arerank", fake_arerank)
    monkeypatch.setattr(core.litellm, "completion_cost", lambda completion_response=None: 0.0001)

    key = (await admin_client.post("/admin/keys", json={"name": "r"})).json()["key"]
    r = await client.post("/v1/rerank", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "rerank-v3.5", "query": "q", "documents": ["a", "b"], "top_n": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "rerank-v3.5"
    assert body["results"][0]["relevance_score"] == 0.98
    assert captured["model"] == "cohere/rerank-v3.5"
    assert captured["query"] == "q" and captured["documents"] == ["a", "b"]

    await _drain()
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.cost_usd == pytest.approx(0.0001)


@pytest.mark.asyncio
async def test_responses(admin_client, client, monkeypatch):
    from app.services import router as core

    async def fake_aresponses(**kwargs):
        return _Fake({
            "id": "resp_1", "object": "response", "model": "openai/gpt-5-responses",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "hi"}]}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        })
    monkeypatch.setattr(core.litellm, "aresponses", fake_aresponses)
    monkeypatch.setattr(core.litellm, "completion_cost", lambda completion_response=None: 0.00002)

    key = (await admin_client.post("/admin/keys", json={"name": "resp"})).json()["key"]
    r = await client.post("/v1/responses", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "gpt-5-responses", "input": "hello"})
    assert r.status_code == 200
    assert r.json()["model"] == "gpt-5-responses"
    assert r.json()["output"][0]["content"][0]["text"] == "hi"

    await _drain()
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.total_tokens == 8


@pytest.mark.asyncio
async def test_rerank_unknown_model_404(admin_client, client):
    key = (await admin_client.post("/admin/keys", json={"name": "r"})).json()["key"]
    r = await client.post("/v1/rerank", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "nope", "query": "q", "documents": ["a"]})
    assert r.status_code == 404
