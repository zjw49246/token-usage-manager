"""P25 回归测试：组织级请求日志 + CSV 导出"""
import asyncio

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion():
    return {"id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.mark.asyncio
async def test_org_usage_log_and_export(monkeypatch):
    from app.services import router as core
    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    async with await _client() as c:
        tok = (await c.post("/auth/register", json={"email": "log@e.com", "password": "password123", "name": "L"})).json()["access_token"]
        oid = (await c.get("/orgs", headers=_auth(tok))).json()[0]["id"]
        key = (await c.post(f"/orgs/{oid}/keys", headers=_auth(tok), json={"name": "k"})).json()["key"]

        # 产生 2 条请求
        for _ in range(2):
            await c.post("/v1/chat/completions", headers=_auth(key),
                         json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
        await asyncio.sleep(0.05)

        # 组织级日志
        r = await c.get(f"/orgs/{oid}/usage", headers=_auth(tok))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert body["items"][0]["model"] == "gemini-2.0-flash"
        assert body["items"][0]["total_tokens"] == 30

        # 按状态过滤（success）
        r2 = await c.get(f"/orgs/{oid}/usage", headers=_auth(tok), params={"status": "success"})
        assert r2.json()["total"] == 2
        r3 = await c.get(f"/orgs/{oid}/usage", headers=_auth(tok), params={"status": "error"})
        assert r3.json()["total"] == 0

        # CSV 导出
        exp = await c.get(f"/orgs/{oid}/usage/export", headers=_auth(tok))
        assert exp.status_code == 200
        assert "text/csv" in exp.headers["content-type"]
        lines = exp.text.strip().split("\n")
        assert lines[0].startswith("time,model,provider")
        assert len(lines) == 3  # 表头 + 2 行


@pytest.mark.asyncio
async def test_org_usage_requires_membership():
    async with await _client() as c:
        a = (await c.post("/auth/register", json={"email": "a@e.com", "password": "password123", "name": "A"})).json()["access_token"]
        b = (await c.post("/auth/register", json={"email": "b@e.com", "password": "password123", "name": "B"})).json()["access_token"]
        oid_a = (await c.get("/orgs", headers=_auth(a))).json()[0]["id"]
        assert (await c.get(f"/orgs/{oid_a}/usage", headers=_auth(b))).status_code == 403
