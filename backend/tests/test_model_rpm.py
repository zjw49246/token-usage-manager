"""P26 回归测试：按模型限速"""
import asyncio

import pytest
from fastapi.responses import JSONResponse


@pytest.mark.asyncio
async def test_per_model_rpm(admin_client, client, monkeypatch):
    from app.routers import proxy as proxy_router
    from app.services import quota

    # 清理内存窗口，避免跨测试污染
    quota._rpm_windows.clear()
    quota._model_rpm_windows.clear()

    async def fake_route(api_key, routes, body):
        return JSONResponse(content={"ok": True})
    monkeypatch.setattr(proxy_router.model_router, "resolve_routes", lambda db, m: asyncio.sleep(0, result=[object()]))
    monkeypatch.setattr(proxy_router.model_router, "route_chat_completion", fake_route)

    created = (await admin_client.post("/admin/keys", json={
        "name": "mrpm", "model_rpm": {"gemini-2.0-flash": 2},
    })).json()
    assert created["model_rpm"] == {"gemini-2.0-flash": 2}
    key = created["key"]
    h = {"Authorization": f"Bearer {key}"}
    body = {"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "x"}]}

    # 前 2 次放行，第 3 次超出该模型 RPM → 429
    r1 = await client.post("/v1/chat/completions", headers=h, json=body)
    r2 = await client.post("/v1/chat/completions", headers=h, json=body)
    r3 = await client.post("/v1/chat/completions", headers=h, json=body)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r3.status_code == 429
    assert "gemini-2.0-flash" in r3.json()["detail"]

    # 另一个模型不受该限速影响（不在 model_rpm 中）
    other = {"model": "gemini-2.5-pro", "messages": [{"role": "user", "content": "x"}]}
    r = await client.post("/v1/chat/completions", headers=h, json=other)
    assert r.status_code == 200
