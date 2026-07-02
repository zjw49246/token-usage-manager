"""P7 回归测试：响应缓存（去重复用 + 命中计费 + 不缓存流式）"""
import asyncio

import pytest
from sqlalchemy import select

from tests.conftest import TestSessionLocal


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion(text="cached-me"):
    return {
        "id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
    }


async def _drain():
    await asyncio.sleep(0.05)


def _count_upstream(monkeypatch):
    from app.services import router as core
    calls = {"n": 0}

    async def fake_acompletion(**kwargs):
        calls["n"] += 1
        return _FakeResp(_completion())

    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)
    return calls


BODY = {"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "cache this"}]}


@pytest.mark.asyncio
async def test_identical_request_served_from_cache(admin_client, client, monkeypatch):
    calls = _count_upstream(monkeypatch)
    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    h = {"Authorization": f"Bearer {key}"}

    r1 = await client.post("/v1/chat/completions", headers=h, json=BODY)
    r2 = await client.post("/v1/chat/completions", headers=h, json=BODY)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["choices"][0]["message"]["content"] == r2.json()["choices"][0]["message"]["content"]
    # 上游只被调用一次，第二次命中缓存
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_different_request_misses(admin_client, client, monkeypatch):
    calls = _count_upstream(monkeypatch)
    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    h = {"Authorization": f"Bearer {key}"}

    await client.post("/v1/chat/completions", headers=h, json=BODY)
    await client.post("/v1/chat/completions", headers=h,
                      json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "different"}]})
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_cache_hit_billed_at_multiplier(admin_client, client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "cache_hit_cost_multiplier", 0.0)
    _count_upstream(monkeypatch)
    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    h = {"Authorization": f"Bearer {key}"}

    await client.post("/v1/chat/completions", headers=h, json=BODY)
    await _drain()
    await client.post("/v1/chat/completions", headers=h, json=BODY)  # cache hit
    await _drain()

    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        recs = (await db.execute(select(UsageRecord).order_by(UsageRecord.id))).scalars().all()
        assert len(recs) == 2
        miss, hit = recs
        assert miss.cached is False and miss.cost_usd == pytest.approx(0.00009)
        assert hit.cached is True and hit.cost_usd == 0.0          # multiplier 0 → 免费
        assert hit.provider == "cache"
        assert hit.total_tokens == 300                            # tokens 仍记录


@pytest.mark.asyncio
async def test_streaming_not_cached(admin_client, client, monkeypatch):
    from app.services import router as core
    calls = {"n": 0}

    async def fake_acompletion(**kwargs):
        calls["n"] += 1
        async def gen():
            for c in [
                {"choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": "stop"}], "model": "gemini/gemini-2.0-flash"},
                {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": "gemini/gemini-2.0-flash"},
            ]:
                yield _FakeResp(c)
        return gen()

    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)
    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    h = {"Authorization": f"Bearer {key}"}
    sbody = {**BODY, "stream": True}
    await client.post("/v1/chat/completions", headers=h, json=sbody)
    await client.post("/v1/chat/completions", headers=h, json=sbody)
    # 流式不缓存 → 两次都打上游
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_cache_disabled(admin_client, client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "cache_enabled", False)
    calls = _count_upstream(monkeypatch)
    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    h = {"Authorization": f"Bearer {key}"}
    await client.post("/v1/chat/completions", headers=h, json=BODY)
    await client.post("/v1/chat/completions", headers=h, json=BODY)
    assert calls["n"] == 2  # 关缓存后每次都打上游
