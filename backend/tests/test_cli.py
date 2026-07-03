"""P12 回归测试：CLI 命令（对 ASGI app 跑真实请求）"""
import json

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app import cli


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    cfgp = tmp_path / "config.json"
    monkeypatch.setattr(cli, "CONFIG_PATH", cfgp)
    return cfgp


class _SyncOverAsgi:
    """把 CLI 的同步 client 调用桥接到 ASGI 测试 app（避免起真实服务）"""
    def __init__(self):
        self._ac = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        self.headers = {}

    def _run(self, coro):
        import anyio
        return anyio.from_thread.run(lambda: coro) if False else anyio.run(lambda: coro)


def _cli_client(cfg):
    """构造一个用 ASGITransport 的同步风格 client（用 httpx.Client 不行，这里用轻封装）"""
    import anyio

    class C:
        def __init__(self):
            self.base = cfg.get("base_url", "http://test")
            self.token = cfg.get("access_token")

        def _headers(self):
            return {"Authorization": f"Bearer {self.token}"} if self.token else {}

        def _do(self, method, path, **kw):
            async def go():
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=self._headers()) as ac:
                    return await ac.request(method, path, **kw)
            return anyio.run(go)

        def get(self, path, **kw): return self._do("GET", path, **kw)
        def post(self, path, **kw): return self._do("POST", path, **kw)
        def delete(self, path, **kw): return self._do("DELETE", path, **kw)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    return C()


@pytest.fixture(autouse=True)
def patch_client(monkeypatch):
    monkeypatch.setattr(cli, "make_client", lambda cfg: _cli_client(cfg))


async def _register(email):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/auth/register", json={"email": email, "password": "password123", "name": "CLI"})


def test_login_and_keys_and_usage(tmp_config, capsys):
    import anyio
    anyio.run(lambda: _register("cli@example.com"))

    cli.main(["login", "-e", "cli@example.com", "-p", "password123"])
    out = capsys.readouterr().out
    assert "已登录 cli@example.com" in out
    cfg = json.loads(tmp_config.read_text())
    assert cfg["access_token"] and cfg["org_id"]

    # 建 Key
    cli.main(["keys", "create", "--name", "from-cli", "--max-cost", "5"])
    assert "新 Key" in capsys.readouterr().out

    # 列 Key
    cli.main(["keys"])
    assert "from-cli" in capsys.readouterr().out

    # 用量总览
    cli.main(["usage"])
    assert "累计成本" in capsys.readouterr().out


def test_models_command(tmp_config, capsys):
    import anyio
    anyio.run(lambda: _register("cli2@example.com"))
    cli.main(["login", "-e", "cli2@example.com", "-p", "password123"])
    capsys.readouterr()
    cli.main(["models", "--mode", "chat"])
    out = capsys.readouterr().out
    assert "gemini-2.0-flash" in out
    assert "共" in out


def test_config_base(tmp_config, capsys):
    cli.main(["config", "--base", "https://example.com/"])
    assert "https://example.com" in capsys.readouterr().out
