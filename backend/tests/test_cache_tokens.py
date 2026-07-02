"""P27 回归测试：上游 prompt 缓存读 token 折扣计费"""
import asyncio

import pytest
from sqlalchemy import select

from tests.conftest import TestSessionLocal


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion_with_cache(prompt=1000, cached=800, completion=200):
    return {
        "id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion,
            "prompt_tokens_details": {"cached_tokens": cached},
        },
    }


@pytest.mark.asyncio
async def test_cached_tokens_discount_billing(admin_client, client, monkeypatch):
    from app.services import router as core
    from app.config import settings
    monkeypatch.setattr(settings, "cache_read_price_ratio", 0.25)
    monkeypatch.setattr(settings, "cache_enabled", False)  # 关响应缓存，只测上游 prompt 缓存计费

    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion_with_cache())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "c"})).json()["key"]
    r = await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200
    await asyncio.sleep(0.05)

    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.cached_tokens == 800
        # in_price 0.1/1M, out 0.4/1M；缓存 800 按 0.25 折扣
        # (1000-800)*0.1/1e6 + 800*0.1*0.25/1e6 + 200*0.4/1e6
        expected = 200 / 1e6 * 0.1 + 800 / 1e6 * 0.1 * 0.25 + 200 / 1e6 * 0.4
        assert rec.cost_usd == pytest.approx(round(expected, 8))


@pytest.mark.asyncio
async def test_no_cached_tokens_full_price(admin_client, client, monkeypatch):
    from app.services import router as core
    from app.config import settings
    monkeypatch.setattr(settings, "cache_enabled", False)

    async def fake_acompletion(**kwargs):
        return _FakeResp({
            "id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
        })
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    key = (await admin_client.post("/admin/keys", json={"name": "c"})).json()["key"]
    await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                      json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
    await asyncio.sleep(0.05)
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.cached_tokens is None
        assert rec.cost_usd == pytest.approx(100 / 1e6 * 0.1 + 200 / 1e6 * 0.4)
