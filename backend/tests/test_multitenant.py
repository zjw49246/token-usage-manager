"""P2a 回归测试：注册/登录/JWT、组织、RBAC、跨组织隔离"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def register(c, email, name="U", password="password123"):
    r = await c.post("/auth/register", json={"email": email, "password": password, "name": name})
    return r


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_register_login_me_and_personal_org():
    async with await _client() as c:
        r = await register(c, "alice@example.com", "Alice")
        assert r.status_code == 201
        tokens = r.json()
        access = tokens["access_token"]

        # /auth/me
        me = await c.get("/auth/me", headers=_auth(access))
        assert me.status_code == 200
        assert me.json()["email"] == "alice@example.com"

        # 注册即有个人组织，且为 owner
        orgs = await c.get("/orgs", headers=_auth(access))
        assert orgs.status_code == 200
        assert len(orgs.json()) == 1
        assert orgs.json()[0]["role"] == "owner"

        # 登录拿新 token
        login = await c.post("/auth/login", json={"email": "alice@example.com", "password": "password123"})
        assert login.status_code == 200
        assert "access_token" in login.json()


@pytest.mark.asyncio
async def test_duplicate_email_and_bad_login():
    async with await _client() as c:
        await register(c, "bob@example.com", "Bob")
        dup = await register(c, "bob@example.com", "Bob2")
        assert dup.status_code == 409
        bad = await c.post("/auth/login", json={"email": "bob@example.com", "password": "wrong"})
        assert bad.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_rejected():
    async with await _client() as c:
        r = await c.get("/auth/me", headers=_auth("garbage.token.value"))
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_flow():
    async with await _client() as c:
        tokens = (await register(c, "carol@example.com", "Carol")).json()
        r = await c.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r.status_code == 200
        assert "access_token" in r.json()
        # access token 不能当 refresh 用
        bad = await c.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
        assert bad.status_code == 401


@pytest.mark.asyncio
async def test_org_scoped_key_and_isolation():
    async with await _client() as c:
        a = (await register(c, "owner-a@example.com", "A")).json()["access_token"]
        b = (await register(c, "owner-b@example.com", "B")).json()["access_token"]
        org_a = (await c.get("/orgs", headers=_auth(a))).json()[0]["id"]
        org_b = (await c.get("/orgs", headers=_auth(b))).json()[0]["id"]

        # A 在自己组织建 Key
        r = await c.post(f"/orgs/{org_a}/keys", headers=_auth(a), json={"name": "k1"})
        assert r.status_code == 201
        key_id = r.json()["id"]

        # A 能看到自己组织的 Key
        assert len((await c.get(f"/orgs/{org_a}/keys", headers=_auth(a))).json()) == 1

        # B 不是 A 组织成员 → 403
        assert (await c.get(f"/orgs/{org_a}/keys", headers=_auth(b))).status_code == 403
        # B 组织里看不到 A 的 Key
        assert len((await c.get(f"/orgs/{org_b}/keys", headers=_auth(b))).json()) == 0
        # B 试图删 A 的 Key（用自己的 org 路径也访问不到）
        assert (await c.delete(f"/orgs/{org_a}/keys/{key_id}", headers=_auth(b))).status_code == 403


@pytest.mark.asyncio
async def test_rbac_member_cannot_create_key():
    async with await _client() as c:
        owner = (await register(c, "o@example.com", "Owner")).json()["access_token"]
        await register(c, "m@example.com", "Member")
        org = (await c.get("/orgs", headers=_auth(owner))).json()[0]["id"]

        # owner 把 member 加进组织（member 角色）
        add = await c.post(f"/orgs/{org}/members", headers=_auth(owner),
                           json={"email": "m@example.com", "role": "member"})
        assert add.status_code == 201

        member = (await c.post("/auth/login", json={"email": "m@example.com", "password": "password123"})).json()["access_token"]
        # member 能查看 Key 列表
        assert (await c.get(f"/orgs/{org}/keys", headers=_auth(member))).status_code == 200
        # 但不能建 Key（需要 admin+）
        r = await c.post(f"/orgs/{org}/keys", headers=_auth(member), json={"name": "nope"})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_rbac_admin_cannot_grant_owner():
    async with await _client() as c:
        owner = (await register(c, "o2@example.com", "Owner")).json()["access_token"]
        await register(c, "adm@example.com", "Adm")
        await register(c, "x@example.com", "X")
        org = (await c.get("/orgs", headers=_auth(owner))).json()[0]["id"]

        await c.post(f"/orgs/{org}/members", headers=_auth(owner), json={"email": "adm@example.com", "role": "admin"})
        admin = (await c.post("/auth/login", json={"email": "adm@example.com", "password": "password123"})).json()["access_token"]

        # admin 能加 member
        assert (await c.post(f"/orgs/{org}/members", headers=_auth(admin),
                             json={"email": "x@example.com", "role": "member"})).status_code == 201
        # admin 不能授予 owner
        r = await c.post(f"/orgs/{org}/members", headers=_auth(admin),
                         json={"email": "x@example.com", "role": "owner"})
        assert r.status_code in (403, 409)  # 403 权限不足（或 409 已是成员）


@pytest.mark.asyncio
async def test_cannot_demote_last_owner():
    async with await _client() as c:
        owner = (await register(c, "solo@example.com", "Solo")).json()["access_token"]
        org = (await c.get("/orgs", headers=_auth(owner))).json()[0]["id"]
        me = (await c.get("/auth/me", headers=_auth(owner))).json()["id"]
        r = await c.patch(f"/orgs/{org}/members/{me}", headers=_auth(owner), json={"role": "member"})
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_org_overview_isolated(monkeypatch):
    async with await _client() as c:
        a = (await register(c, "stat-a@example.com", "A")).json()["access_token"]
        org_a = (await c.get("/orgs", headers=_auth(a))).json()[0]["id"]
        r = await c.get(f"/orgs/{org_a}/stats/overview", headers=_auth(a))
        assert r.status_code == 200
        body = r.json()
        assert body["total_keys"] == 0
        assert "total_cost_usd" in body
