"""P21 回归测试：Prometheus /metrics"""
import asyncio

import pytest


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion():
    return {"id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}}


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus(admin_client, client):
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "# TYPE" in r.text  # Prometheus 暴露格式（带标签的自定义计数器首次使用后才出现）


@pytest.mark.asyncio
async def test_metrics_increment_on_request(admin_client, client, monkeypatch):
    from app.services import router as core
    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "m"})).json()["key"]
    await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                      json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
    await asyncio.sleep(0.05)  # 等后台记账触发指标

    r = await client.get("/metrics")
    body = r.text
    assert 'tr_requests_total{cached="false",model="gemini-2.0-flash"' in body
    assert "tr_tokens_total" in body
