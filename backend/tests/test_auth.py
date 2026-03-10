import pytest
from app.services.auth import generate_api_key, hash_key


def test_generate_api_key_format():
    raw, key_hash, prefix = generate_api_key()
    assert raw.startswith("tum_")
    assert len(key_hash) == 64
    assert raw.startswith(prefix)


def test_hash_deterministic():
    raw, h1, _ = generate_api_key()
    h2 = hash_key(raw)
    assert h1 == h2


def test_different_keys_different_hashes():
    _, h1, _ = generate_api_key()
    _, h2, _ = generate_api_key()
    assert h1 != h2


@pytest.mark.asyncio
async def test_create_and_verify_key(admin_client, client):
    # 创建 key
    resp = await admin_client.post("/admin/keys", json={"name": "test-app"})
    assert resp.status_code == 201
    data = resp.json()
    assert "key" in data
    assert data["key"].startswith("tum_")

    # 用生成的 key 访问 /v1/models
    resp2 = await client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {data['key']}"},
    )
    assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_invalid_key_rejected(client):
    resp = await client.get(
        "/v1/models",
        headers={"Authorization": "Bearer tum_invalid"},
    )
    assert resp.status_code == 401
