"""P19 回归测试：站内 Playground 试聊"""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from tests.conftest import TestSessionLocal


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion(text="playground reply"):
    return {"id": "x", "object": "chat.completion", "model": "gemini/gemini-2.0-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}}


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.mark.asyncio
async def test_playground_chat(monkeypatch):
    from app.services import router as core
    async def fake_acompletion(**kwargs):
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    async with await _client() as c:
        tok = (await c.post("/auth/register", json={"email": "pg@e.com", "password": "password123", "name": "PG"})).json()["access_token"]
        oid = (await c.get("/orgs", headers=_auth(tok))).json()[0]["id"]

        r = await c.post(f"/orgs/{oid}/playground/chat", headers=_auth(tok),
                         json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 200
        assert r.json()["choices"][0]["message"]["content"] == "playground reply"

        # Playground 隐藏 Key 不出现在 Key 列表
        keys = (await c.get(f"/orgs/{oid}/keys", headers=_auth(tok))).json()
        assert all(k["name"] != "__playground__" for k in keys)


@pytest.mark.asyncio
async def test_playground_requires_membership(monkeypatch):
    async with await _client() as c:
        a = (await c.post("/auth/register", json={"email": "a@e.com", "password": "password123", "name": "A"})).json()["access_token"]
        b = (await c.post("/auth/register", json={"email": "b@e.com", "password": "password123", "name": "B"})).json()["access_token"]
        oid_a = (await c.get("/orgs", headers=_auth(a))).json()[0]["id"]
        # B 不是 A 组织成员 → 403
        r = await c.post(f"/orgs/{oid_a}/playground/chat", headers=_auth(b),
                         json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]})
        assert r.status_code == 403
