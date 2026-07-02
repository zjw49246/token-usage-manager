"""P22 回归测试：模型别名"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


class _FakeResp:
    def __init__(self, d): self._d = d
    def model_dump(self, exclude_none=True): return dict(self._d)


def _completion(model="gemini/gemini-2.0-flash"):
    return {"id": "x", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


async def _superadmin(c, email="sa@e.com"):
    tok = (await c.post("/auth/register", json={"email": email, "password": "password123", "name": "SA"})).json()["access_token"]
    await c.post("/admin/superadmin", headers={"Authorization": "Bearer test-admin-token"}, json={"email": email})
    return tok


@pytest.mark.asyncio
async def test_alias_crud_and_routing(admin_client, client, monkeypatch):
    from app.services import router as core
    captured = {}
    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeResp(_completion())
    monkeypatch.setattr(core.litellm, "acompletion", fake_acompletion)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        tok = await _superadmin(c)
        h = {"Authorization": f"Bearer {tok}"}
        # 建别名 fast → gemini-2.0-flash
        r = await c.post("/aliases", headers=h, json={"alias": "fast", "target_model_id": "gemini-2.0-flash"})
        assert r.status_code == 201
        assert (await c.get("/aliases", headers=h)).json()[0]["alias"] == "fast"

    # 用别名调用 → 路由到目标模型
    key = (await admin_client.post("/admin/keys", json={"name": "k"})).json()["key"]
    r = await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                          json={"model": "fast", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200
    assert captured["model"] == "gemini/gemini-2.0-flash"  # 别名解析到真实上游模型


@pytest.mark.asyncio
async def test_alias_unknown_target_404(client):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        tok = await _superadmin(c, "sa2@e.com")
        r = await c.post("/aliases", headers={"Authorization": f"Bearer {tok}"},
                         json={"alias": "x", "target_model_id": "no-such-model"})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_alias_requires_superadmin(client):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        tok = (await c.post("/auth/register", json={"email": "u@e.com", "password": "password123", "name": "U"})).json()["access_token"]
        assert (await c.get("/aliases", headers={"Authorization": f"Bearer {tok}"})).status_code == 403
