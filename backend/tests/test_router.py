"""P1 回归测试：LiteLLM 路由内核 + 成本核算 + 目录驱动 /v1/models"""
import asyncio
import json

import pytest
from sqlalchemy import select

from tests.conftest import TestSessionLocal


class _FakeResponse:
    """模拟 litellm ModelResponse（只需 model_dump）"""

    def __init__(self, data: dict):
        self._data = data

    def model_dump(self, exclude_none=True):
        return dict(self._data)


def _fake_completion_payload(model="gemini/gemini-2.0-flash"):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
    }


async def _drain_bg_tasks():
    """等待 fire-and-forget 的记账 task 完成"""
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_models_endpoint_returns_pricing(admin_client, client):
    """/v1/models 从目录返回，带价格/上下文窗口扩展字段"""
    key = (await admin_client.post("/admin/keys", json={"name": "m"})).json()["key"]
    resp = await client.get("/v1/models", headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 200
    data = {m["id"]: m for m in resp.json()["data"]}
    assert "gemini-2.0-flash" in data
    m = data["gemini-2.0-flash"]
    assert m["owned_by"] == "google"
    assert m["input_price_per_1m"] == 0.1
    assert m["output_price_per_1m"] == 0.4
    assert m["context_window"] == 1048576


@pytest.mark.asyncio
async def test_unknown_model_404(admin_client, client):
    """不在目录中的模型 → OpenAI 风格 404 model_not_found"""
    key = (await admin_client.post("/admin/keys", json={"name": "u"})).json()["key"]
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "no-such-model", "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "model_not_found"


@pytest.mark.asyncio
async def test_nonstream_completion_records_cost(admin_client, client, monkeypatch):
    """非流式：litellm 返回 usage → 按目录单价记 cost_usd 并原子累加"""
    from app.services import router as model_router

    captured_kwargs = {}

    async def fake_acompletion(**kwargs):
        captured_kwargs.update(kwargs)
        return _FakeResponse(_fake_completion_payload())

    monkeypatch.setattr(model_router.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "c"})).json()["key"]
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "gemini-2.0-flash"  # 对外回显公开名
    assert captured_kwargs["model"] == "gemini/gemini-2.0-flash"  # 上游用 litellm 全名

    await _drain_bg_tasks()
    from app.models import UsageRecord, UsageSummary
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        # 100/1M*0.1 + 200/1M*0.4 = 0.00001 + 0.00008 = 0.00009
        assert rec.cost_usd == pytest.approx(0.00009)
        assert rec.provider == "google"
        summary = (await db.execute(select(UsageSummary))).scalar_one()
        assert summary.total_cost_usd == pytest.approx(0.00009)
        assert summary.total_tokens_used == 300


@pytest.mark.asyncio
async def test_max_cost_usd_quota(admin_client, client, monkeypatch):
    """USD 成本限额：累计成本达到 max_cost_usd 后拒绝（429）"""
    from app.services import router as model_router

    async def fake_acompletion(**kwargs):
        return _FakeResponse(_fake_completion_payload())

    monkeypatch.setattr(model_router.litellm, "acompletion", fake_acompletion)

    created = (await admin_client.post(
        "/admin/keys", json={"name": "cost-cap", "max_cost_usd": 0.00005},
    )).json()
    key = created["key"]
    headers = {"Authorization": f"Bearer {key}"}
    payload = {"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]}

    # 第一次：额度未用，放行（记账后成本 0.00009 > 0.00005）
    r1 = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert r1.status_code == 200
    await _drain_bg_tasks()

    # 第二次：预检发现累计成本已超限 → 429
    r2 = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert r2.status_code == 429
    assert "Cost quota" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_stream_completion_sse_and_usage(admin_client, client, monkeypatch):
    """流式：回吐 OpenAI SSE（含 [DONE]），从尾部 chunk 提取 usage 并记账"""
    from app.services import router as model_router

    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "model": "gemini/gemini-2.0-flash",
         "choices": [{"index": 0, "delta": {"content": "he"}}]},
        {"id": "c1", "object": "chat.completion.chunk", "model": "gemini/gemini-2.0-flash",
         "choices": [{"index": 0, "delta": {"content": "llo"}, "finish_reason": "stop"}]},
        {"id": "c1", "object": "chat.completion.chunk", "model": "gemini/gemini-2.0-flash",
         "choices": [],
         "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}},
    ]

    async def fake_acompletion(**kwargs):
        async def gen():
            for c in chunks:
                yield _FakeResponse(c)
        return gen()

    monkeypatch.setattr(model_router.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "s"})).json()["key"]
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "gemini-2.0-flash", "stream": True,
              "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 200
    text = resp.text
    lines = [l for l in text.split("\n") if l.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    first = json.loads(lines[0][6:])
    assert first["model"] == "gemini-2.0-flash"  # 公开名回显
    assert first["choices"][0]["delta"]["content"] == "he"

    await _drain_bg_tasks()
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.total_tokens == 30
        assert rec.cost_usd == pytest.approx(10 / 1e6 * 0.1 + 20 / 1e6 * 0.4)


@pytest.mark.asyncio
async def test_upstream_error_mapped(admin_client, client, monkeypatch):
    """上游异常按 status_code 映射回客户端，并记 error 明细"""
    from app.services import router as model_router

    class FakeUpstreamError(Exception):
        status_code = 429
        message = "rate limited by upstream"

    async def fake_acompletion(**kwargs):
        raise FakeUpstreamError()

    monkeypatch.setattr(model_router.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "e"})).json()["key"]
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 429
    assert "rate limited" in resp.json()["detail"]

    await _drain_bg_tasks()
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.status == "error"
