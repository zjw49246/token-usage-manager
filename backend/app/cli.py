"""TokenRouter CLI（P12）：命令行管理登录 / 模型 / Key / 用量。

安装后用 `tr <命令>`；配置存 ~/.tokenrouter/config.json。
  tr config --base https://token-router.claude-code-manager.com
  tr login -e you@example.com          # 交互输入密码
  tr models [--provider openai] [--mode chat]
  tr keys                              # 列出当前组织的 Key
  tr keys create --name app --max-cost 10
  tr keys rm <id>
  tr usage                             # 当前组织用量总览
  tr orgs | tr use <org_id>
"""
import argparse
import getpass
import json
import os
import sys
from pathlib import Path

import httpx

CONFIG_PATH = Path(os.environ.get("TR_CONFIG", str(Path.home() / ".tokenrouter" / "config.json")))
DEFAULT_BASE = os.environ.get("TR_BASE_URL", "http://localhost:8000")


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {"base_url": DEFAULT_BASE}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def make_client(cfg: dict) -> httpx.Client:
    headers = {}
    if cfg.get("access_token"):
        headers["Authorization"] = f"Bearer {cfg['access_token']}"
    return httpx.Client(base_url=cfg.get("base_url", DEFAULT_BASE), headers=headers, timeout=30)


def _die(msg: str):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(1)


def _require_org(cfg: dict) -> int:
    oid = cfg.get("org_id")
    if not oid:
        _die("未选择组织，先 `tr login` 或 `tr use <org_id>`")
    return oid


# ── 命令实现 ──

def cmd_config(args, cfg, client):
    if args.base:
        cfg["base_url"] = args.base.rstrip("/")
        save_config(cfg)
    print(f"base_url = {cfg.get('base_url', DEFAULT_BASE)}")


def cmd_login(args, cfg, client):
    password = args.password or getpass.getpass("密码: ")
    r = client.post("/auth/login", json={"email": args.email, "password": password})
    if r.status_code != 200:
        _die(r.json().get("detail", "登录失败"))
    tokens = r.json()
    cfg.update(access_token=tokens["access_token"], refresh_token=tokens["refresh_token"])
    # 拉组织，默认选第一个
    orgs = make_client(cfg).get("/orgs").json()
    if orgs:
        cfg["org_id"] = orgs[0]["id"]
    save_config(cfg)
    print(f"已登录 {args.email}" + (f"，当前组织 #{cfg.get('org_id')}" if cfg.get("org_id") else ""))


def cmd_orgs(args, cfg, client):
    for o in client.get("/orgs").json():
        cur = " *" if o["id"] == cfg.get("org_id") else ""
        print(f"#{o['id']:<4} {o['name']:<28} {o['role']:<8}{cur}")


def cmd_use(args, cfg, client):
    cfg["org_id"] = args.org_id
    save_config(cfg)
    print(f"当前组织 = #{args.org_id}")


def cmd_models(args, cfg, client):
    params = {}
    if args.provider:
        params["provider"] = args.provider
    data = client.get("/catalog/models", params=params).json()["data"]
    if args.mode:
        data = [m for m in data if m.get("mode") == args.mode]
    for m in data:
        price = (f"${m['input_price_per_1m']}/{m['output_price_per_1m']} per1M"
                 if m["mode"] != "image" else f"${m.get('image_price')}/img")
        print(f"{m['id']:<38} {m['provider']:<14} {m['mode']:<10} {price}")
    print(f"\n共 {len(data)} 个模型")


def cmd_keys(args, cfg, client):
    oid = _require_org(cfg)
    for k in client.get(f"/orgs/{oid}/keys").json():
        u = k.get("usage") or {}
        print(f"#{k['id']:<4} {k['name']:<24} {k['key_prefix']}...  "
              f"calls={u.get('total_calls', 0)} cost=${u.get('total_cost_usd', 0):.4f} "
              f"{'启用' if k['is_active'] else '停用'}")


def cmd_keys_create(args, cfg, client):
    oid = _require_org(cfg)
    payload = {"name": args.name}
    if args.max_cost:
        payload["max_cost_usd"] = args.max_cost
    r = client.post(f"/orgs/{oid}/keys", json=payload)
    if r.status_code != 201:
        _die(r.json().get("detail", "创建失败"))
    print("新 Key（仅此一次显示）:", r.json()["key"])


def cmd_keys_rm(args, cfg, client):
    oid = _require_org(cfg)
    r = client.delete(f"/orgs/{oid}/keys/{args.id}")
    print("已删除" if r.status_code == 204 else f"失败: {r.status_code}")


def cmd_usage(args, cfg, client):
    oid = _require_org(cfg)
    s = client.get(f"/orgs/{oid}/stats/overview").json()
    print(f"累计成本 ${s['total_cost_usd']:.4f} | 今日 ${s['today_cost_usd']:.4f}")
    print(f"累计 tokens {s['total_tokens']} | 调用 {s['total_calls']} | 今日调用 {s['today_calls']}")
    print(f"Key: {s['active_keys']}/{s['total_keys']} 启用")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tr", description="TokenRouter CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("config"); c.add_argument("--base"); c.set_defaults(func=cmd_config)
    lo = sub.add_parser("login"); lo.add_argument("-e", "--email", required=True); lo.add_argument("-p", "--password"); lo.set_defaults(func=cmd_login)
    sub.add_parser("orgs").set_defaults(func=cmd_orgs)
    u = sub.add_parser("use"); u.add_argument("org_id", type=int); u.set_defaults(func=cmd_use)
    m = sub.add_parser("models"); m.add_argument("--provider"); m.add_argument("--mode", choices=["chat", "embedding", "image"]); m.set_defaults(func=cmd_models)

    k = sub.add_parser("keys"); ksub = k.add_subparsers(dest="kcmd")
    k.set_defaults(func=cmd_keys)
    kc = ksub.add_parser("create"); kc.add_argument("--name", required=True); kc.add_argument("--max-cost", type=float, dest="max_cost"); kc.set_defaults(func=cmd_keys_create)
    kr = ksub.add_parser("rm"); kr.add_argument("id", type=int); kr.set_defaults(func=cmd_keys_rm)

    sub.add_parser("usage").set_defaults(func=cmd_usage)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = load_config()
    with make_client(cfg) as client:
        args.func(args, cfg, client)


if __name__ == "__main__":
    main()
