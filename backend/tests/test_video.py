"""P17 回归测试：/v1/videos/generations 视频生成端点"""
import asyncio

import pytest
from sqlalchemy import select

from tests.conftest import TestSessionLocal


class _Fake:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


@pytest.mark.asyncio
async def test_video_generation(admin_client, client, monkeypatch):
    from app.services import router as core
    captured = {}

    async def fake_avideo(**kwargs):
        captured.update(kwargs)
        return _Fake({"created": 1, "data": [{"url": "http://vid/1.mp4"}], "model": "gemini/veo-3.1-generate-preview"})
    monkeypatch.setattr(core.litellm, "avideo_generation", fake_avideo)
    monkeypatch.setattr(core.litellm, "completion_cost", lambda completion_response=None: 0.5)

    key = (await admin_client.post("/admin/keys", json={"name": "v"})).json()["key"]
    r = await client.post("/v1/videos/generations", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "veo-3.1", "prompt": "a cat surfing"})
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "veo-3.1"
    assert body["data"][0]["url"].endswith(".mp4")
    assert captured["model"] == "gemini/veo-3.1-generate-preview"
    assert captured["prompt"] == "a cat surfing"

    await asyncio.sleep(0.05)
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.cost_usd == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_video_unknown_model_404(admin_client, client):
    key = (await admin_client.post("/admin/keys", json={"name": "v"})).json()["key"]
    r = await client.post("/v1/videos/generations", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "nope", "prompt": "x"})
    assert r.status_code == 404
