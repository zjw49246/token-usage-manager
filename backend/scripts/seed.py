"""P0 Seed 脚本（幂等，可重复执行）：

1. 建供应商注册表（openai / anthropic / google / deepseek / mistral / groq / xai）
2. 从 litellm.model_cost 灌模型目录（单价 / 上下文窗口 / 能力）
3. 保留现有 10 个硬编码模型的目录条目（含火山 Ark 的 DeepSeek 命名），保证行为不变
4. 建默认组织并回填现有 api_keys.org_id / usage_records.org_id

用法： cd backend && uv run python -m scripts.seed
"""
import asyncio
import re

import litellm
from sqlalchemy import select, update

from app.database import AsyncSessionLocal, init_db
from app.models import Provider, ModelCatalog, Organization, ApiKey, UsageRecord

# 供应商注册表：name -> (litellm 前缀, 自定义 api_base, 凭证 env 名)
PROVIDERS: dict[str, tuple[str, str | None, str]] = {
    "openai":    ("openai",    None, "OPENAI_API_KEY"),
    "anthropic": ("anthropic", None, "ANTHROPIC_API_KEY"),
    "google":    ("gemini",    None, "GEMINI_API_KEY"),
    "deepseek":  ("deepseek",  None, "DEEPSEEK_API_KEY"),
    "mistral":   ("mistral",   None, "MISTRAL_API_KEY"),
    "groq":      ("groq",      None, "GROQ_API_KEY"),
    "xai":       ("xai",       None, "XAI_API_KEY"),
}

# litellm_provider -> 我们的 provider name
LITELLM_PROVIDER_MAP = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google",
    "deepseek": "deepseek",
    "mistral": "mistral",
    "groq": "groq",
    "xai": "xai",
}

# 现有部署的 10 个模型（火山 Ark 的 DeepSeek 命名 litellm 价格表里没有，手工给价）
LEGACY_MODELS: list[dict] = [
    # (model_id, provider, litellm_model, in_price/1M, out_price/1M, ctx)
    {"model_id": "deepseek-v3-250324",  "provider": "deepseek", "litellm_model": "deepseek/deepseek-chat",     "in": 0.28, "out": 0.42, "ctx": 131072},
    {"model_id": "deepseek-r1-250528",  "provider": "deepseek", "litellm_model": "deepseek/deepseek-reasoner", "in": 0.55, "out": 2.19, "ctx": 131072},
    {"model_id": "deepseek-v3-2-251201", "provider": "deepseek", "litellm_model": "deepseek/deepseek-chat",    "in": 0.28, "out": 0.42, "ctx": 131072},
]

# 只收录这些模式的模型（chat 为主，后续期再开 embedding / image）
ALLOWED_MODES = {"chat"}

# 过滤掉日期快照、ft、audio/realtime 等长尾命名，保持目录干净
EXCLUDE_PATTERN = re.compile(
    r"(ft:|audio|realtime|search|transcribe|tts|whisper|dall-e|davinci|babbage|curie|"
    r"instruct-0914|-\d{4}(-\d{2}){2}|@|latest$)",
    re.IGNORECASE,
)


def _public_name(litellm_key: str) -> str:
    """litellm 键名转对外公开名：去掉 provider/ 前缀"""
    return litellm_key.split("/", 1)[1] if "/" in litellm_key else litellm_key


def _capabilities(info: dict) -> list[str]:
    caps = ["chat"]
    if info.get("supports_vision"):
        caps.append("vision")
    if info.get("supports_function_calling"):
        caps.append("tools")
    return caps


async def seed_providers(db) -> dict[str, int]:
    """幂等建供应商，返回 name -> id"""
    ids = {}
    for name, (prefix, api_base, cred_env) in PROVIDERS.items():
        row = (await db.execute(select(Provider).where(Provider.name == name))).scalar_one_or_none()
        if row is None:
            row = Provider(name=name, litellm_prefix=prefix, api_base=api_base, credential_env=cred_env, enabled=True)
            db.add(row)
            await db.flush()
        ids[name] = row.id
    await db.commit()
    return ids


async def seed_catalog(db, provider_ids: dict[str, int]) -> tuple[int, int]:
    """从 litellm.model_cost 灌目录，幂等（存在则跳过）。返回 (新增数, 总数)"""
    existing = set((await db.execute(select(ModelCatalog.model_id))).scalars())
    added = 0

    for key, info in litellm.model_cost.items():
        if not isinstance(info, dict):
            continue
        if info.get("mode") not in ALLOWED_MODES:
            continue
        provider = LITELLM_PROVIDER_MAP.get(info.get("litellm_provider", ""))
        if provider is None:
            continue
        if EXCLUDE_PATTERN.search(key):
            continue
        public = _public_name(key)
        if public in existing:
            continue
        in_cost = info.get("input_cost_per_token")
        out_cost = info.get("output_cost_per_token")
        db.add(ModelCatalog(
            model_id=public,
            provider_id=provider_ids[provider],
            litellm_model=key if "/" in key else f"{PROVIDERS[provider][0]}/{key}",
            display_name=public,
            input_price_per_1m=round(in_cost * 1e6, 4) if in_cost else None,
            output_price_per_1m=round(out_cost * 1e6, 4) if out_cost else None,
            context_window=info.get("max_input_tokens"),
            max_output_tokens=info.get("max_output_tokens"),
            capabilities=_capabilities(info),
            verified=False,
            enabled=True,
        ))
        existing.add(public)
        added += 1

    # 现有部署的遗留模型名（保证行为不变）
    for m in LEGACY_MODELS:
        if m["model_id"] in existing:
            continue
        db.add(ModelCatalog(
            model_id=m["model_id"],
            provider_id=provider_ids[m["provider"]],
            litellm_model=m["litellm_model"],
            display_name=m["model_id"],
            input_price_per_1m=m["in"],
            output_price_per_1m=m["out"],
            context_window=m["ctx"],
            capabilities=["chat"],
            verified=True,
            enabled=True,
        ))
        existing.add(m["model_id"])
        added += 1

    await db.commit()
    return added, len(existing)


async def seed_default_org(db) -> None:
    """建默认组织并回填现有 Key / 用量的归属（幂等）"""
    org = (await db.execute(select(Organization).where(Organization.slug == "default"))).scalar_one_or_none()
    if org is None:
        org = Organization(name="Default Organization", slug="default", credit_balance_usd=0.0)
        db.add(org)
        await db.flush()
    await db.execute(update(ApiKey).where(ApiKey.org_id.is_(None)).values(org_id=org.id))
    await db.execute(update(UsageRecord).where(UsageRecord.org_id.is_(None)).values(org_id=org.id))
    await db.commit()


async def main() -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        provider_ids = await seed_providers(db)
        print(f"providers: {len(provider_ids)} -> {sorted(provider_ids)}")
        added, total = await seed_catalog(db, provider_ids)
        print(f"model_catalog: +{added} (total {total})")
        await seed_default_org(db)
        print("default org created & api_keys/usage_records backfilled")


if __name__ == "__main__":
    asyncio.run(main())
