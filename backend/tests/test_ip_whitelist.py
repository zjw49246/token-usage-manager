"""P20 回归测试：API Key IP 白名单"""
import pytest


@pytest.mark.asyncio
async def test_ip_whitelist_allows_and_blocks(admin_client, client):
    created = (await admin_client.post("/admin/keys", json={
        "name": "ip-locked", "allowed_ips": ["1.2.3.4", "10.0.0.0/8"],
    })).json()
    assert created["allowed_ips"] == ["1.2.3.4", "10.0.0.0/8"]
    key = created["key"]
    h = {"Authorization": f"Bearer {key}"}

    # 白名单内单 IP → 放行
    r = await client.get("/v1/models", headers={**h, "cf-connecting-ip": "1.2.3.4"})
    assert r.status_code == 200
    # CIDR 命中 → 放行
    r = await client.get("/v1/models", headers={**h, "cf-connecting-ip": "10.5.6.7"})
    assert r.status_code == 200
    # 不在白名单 → 403
    r = await client.get("/v1/models", headers={**h, "cf-connecting-ip": "9.9.9.9"})
    assert r.status_code == 403
    assert "IP" in r.json()["detail"]


@pytest.mark.asyncio
async def test_no_whitelist_allows_any(admin_client, client):
    key = (await admin_client.post("/admin/keys", json={"name": "open"})).json()["key"]
    r = await client.get("/v1/models", headers={"Authorization": f"Bearer {key}", "cf-connecting-ip": "8.8.8.8"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_ip_whitelist_on_ingress(admin_client, client, monkeypatch):
    """Anthropic 入口也校验 IP 白名单"""
    key = (await admin_client.post("/admin/keys", json={"name": "ipa", "allowed_ips": ["1.1.1.1"]})).json()["key"]
    r = await client.post("/v1/messages",
                          headers={"x-api-key": key, "cf-connecting-ip": "2.2.2.2"},
                          json={"model": "gemini-2.0-flash", "max_tokens": 10, "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 403
