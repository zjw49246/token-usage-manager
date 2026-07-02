"""P29 回归测试：推理后缀 + reasoning_content→<think>"""
import pytest


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion(reasoning=None):
    msg = {"role": "assistant", "content": "answer"}
    if reasoning:
        msg["reasoning_content"] = reasoning
    return {"id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
            "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


@pytest.mark.asyncio
async def test_reasoning_suffix_injects_effort(admin_client, client, monkeypatch):
    from app.services import router as core
    captured = {}
    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    # 目录里有 gemini-2.0-flash，请求 gemini-2.0-flash-low → 注入 reasoning_effort=low，路由到基础模型
    r = await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "gemini-2.0-flash-low", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200
    assert captured["reasoning_effort"] == "low"
    assert captured["model"] == "gemini/gemini-2.0-flash"  # 基础模型上游名
    assert r.json()["model"] == "gemini-2.0-flash"


@pytest.mark.asyncio
async def test_unknown_suffix_base_missing_404(admin_client, client):
    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    # base "no-such" 不在目录 → 404
    r = await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "no-such-high", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reasoning_content_to_think_tags(admin_client, client, monkeypatch):
    from app.services import router as core
    from app.config import settings
    monkeypatch.setattr(settings, "merge_reasoning_content", True)
    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion(reasoning="let me think..."))
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    r = await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
    content = r.json()["choices"][0]["message"]["content"]
    assert content == "<think>let me think...</think>\nanswer"
    assert "reasoning_content" not in r.json()["choices"][0]["message"]
