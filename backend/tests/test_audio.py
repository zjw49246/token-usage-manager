"""P16 回归测试：/v1/audio/speech (TTS) 与 /v1/audio/transcriptions (STT)"""
import asyncio

import pytest
from sqlalchemy import select

from tests.conftest import TestSessionLocal


async def _drain():
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_tts_returns_audio(admin_client, client, monkeypatch):
    from app.services import router as core

    class _Speech:
        content = b"ID3\x00\x00fake-mp3-bytes"

    captured = {}

    async def fake_aspeech(**kwargs):
        captured.update(kwargs)
        return _Speech()
    monkeypatch.setattr(core.litellm, "aspeech", fake_aspeech)
    monkeypatch.setattr(core.litellm, "completion_cost", lambda completion_response=None: 0.00003)

    key = (await admin_client.post("/admin/keys", json={"name": "tts"})).json()["key"]
    r = await client.post("/v1/audio/speech", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "tts-1", "input": "hello world", "voice": "alloy"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/")
    assert r.content == b"ID3\x00\x00fake-mp3-bytes"
    assert captured["model"] == "openai/tts-1"
    assert captured["input"] == "hello world"

    await _drain()
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.cost_usd == pytest.approx(0.00003)


@pytest.mark.asyncio
async def test_stt_transcription(admin_client, client, monkeypatch):
    from app.services import router as core

    class _Tr:
        def model_dump(self, exclude_none=True): return {"text": "transcribed text"}

    captured = {}

    async def fake_atranscription(**kwargs):
        captured.update(kwargs)
        return _Tr()
    monkeypatch.setattr(core.litellm, "atranscription", fake_atranscription)
    monkeypatch.setattr(core.litellm, "completion_cost", lambda completion_response=None: 0.0001)

    key = (await admin_client.post("/admin/keys", json={"name": "stt"})).json()["key"]
    files = {"file": ("clip.mp3", b"fake-audio-bytes", "audio/mpeg")}
    data = {"model": "whisper-1", "language": "en"}
    r = await client.post("/v1/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                          files=files, data=data)
    assert r.status_code == 200
    assert r.json()["text"] == "transcribed text"
    assert captured["model"] == "openai/whisper-1"
    assert captured["language"] == "en"
    assert captured["file"][0] == "clip.mp3" and captured["file"][1] == b"fake-audio-bytes"

    await _drain()
    from app.models import UsageRecord
    async with TestSessionLocal() as db:
        rec = (await db.execute(select(UsageRecord))).scalar_one()
        assert rec.cost_usd == pytest.approx(0.0001)


@pytest.mark.asyncio
async def test_tts_unknown_model_404(admin_client, client):
    key = (await admin_client.post("/admin/keys", json={"name": "x"})).json()["key"]
    r = await client.post("/v1/audio/speech", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "nope", "input": "x", "voice": "alloy"})
    assert r.status_code == 404
