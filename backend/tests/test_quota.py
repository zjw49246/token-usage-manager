import pytest
from datetime import datetime, timezone, timedelta


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_model_restriction(admin_client, client):
    resp = await admin_client.post("/admin/keys", json={
        "name": "restricted",
        "allowed_models": ["gemini-2.0-flash"],
    })
    key = resp.json()["key"]

    # 允许的模型 → 应该能调用（虽然上游会失败，但不应被配额拒绝）
    # 这里只测试配额层，不测试上游转发
    # 直接测 /v1/models 返回的模型列表
    resp2 = await client.get("/v1/models", headers={"Authorization": f"Bearer {key}"})
    assert resp2.status_code == 200
    model_ids = [m["id"] for m in resp2.json()["data"]]
    assert "gemini-2.0-flash" in model_ids
    assert "gemini-2.5-pro" not in model_ids


@pytest.mark.asyncio
async def test_time_restriction_expired(admin_client, client):
    past = _now() - timedelta(days=10)
    past_end = _now() - timedelta(days=1)
    resp = await admin_client.post("/admin/keys", json={
        "name": "expired",
        "valid_from": past.isoformat(),
        "valid_until": past_end.isoformat(),
    })
    key = resp.json()["key"]

    # chat/completions 会触发配额检查
    resp2 = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp2.status_code == 403
    assert "expired" in resp2.json()["detail"]


@pytest.mark.asyncio
async def test_admin_crud(admin_client):
    # 创建
    resp = await admin_client.post("/admin/keys", json={"name": "app-a", "max_calls": 100})
    assert resp.status_code == 201
    key_id = resp.json()["id"]

    # 列表
    resp = await admin_client.get("/admin/keys")
    assert resp.status_code == 200
    assert any(k["id"] == key_id for k in resp.json())

    # 更新
    resp = await admin_client.patch(f"/admin/keys/{key_id}", json={"name": "app-a-renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "app-a-renamed"

    # 停用
    resp = await admin_client.patch(f"/admin/keys/{key_id}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    # 删除
    resp = await admin_client.delete(f"/admin/keys/{key_id}")
    assert resp.status_code == 204

    # 确认已删除
    resp = await admin_client.get(f"/admin/keys/{key_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stats_overview(admin_client):
    resp = await admin_client.get("/admin/stats/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_tokens" in data
    assert "active_keys" in data
