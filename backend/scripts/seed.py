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
    # 火山 Ark（OpenAI 兼容端点）：现有部署的 DeepSeek 走这里，保证行为不变
    "volcengine-ark": ("openai", "https://ark.cn-beijing.volces.com/api/v3", "DEEPSEEK_API_KEY"),
    # 聚合器 / 更多单密钥供应商（P14，扩到 300+ 模型）
    "openrouter":  ("openrouter",  None, "OPENROUTER_API_KEY"),
    "fireworks":   ("fireworks_ai", None, "FIREWORKS_API_KEY"),
    "together":    ("together_ai",  None, "TOGETHER_API_KEY"),
    "deepinfra":   ("deepinfra",   None, "DEEPINFRA_API_KEY"),
    "novita":      ("novita",      None, "NOVITA_API_KEY"),
    "perplexity":  ("perplexity",  None, "PERPLEXITY_API_KEY"),
    "moonshot":    ("moonshot",    None, "MOONSHOT_API_KEY"),
    "nebius":      ("nebius",      None, "NEBIUS_API_KEY"),
    "cohere":      ("cohere",      None, "COHERE_API_KEY"),
    "voyage":      ("voyage",      None, "VOYAGE_API_KEY"),
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
    "openrouter": "openrouter",
    "fireworks_ai": "fireworks",
    "together_ai": "together",
    "deepinfra": "deepinfra",
    "novita": "novita",
    "perplexity": "perplexity",
    "moonshot": "moonshot",
    "nebius": "nebius",
    "cohere": "cohere",
    "cohere_chat": "cohere",
    "voyage": "voyage",
}

# 现有部署的遗留模型（火山 Ark 的 DeepSeek 命名 litellm 价格表里没有，手工给价）。
# litellm_model 用 openai/ 前缀 = 「通用 OpenAI 兼容直通」，配合 provider.api_base 打到 Ark，
# 模型名原样传给上游，行为与旧版 proxy 完全一致。
LEGACY_MODELS: list[dict] = [
    # (model_id, provider, litellm_model, in_price/1M, out_price/1M, ctx)
    {"model_id": "deepseek-v3-250324",   "provider": "volcengine-ark", "litellm_model": "openai/deepseek-v3-250324",   "in": 0.28, "out": 0.42, "ctx": 131072},
    {"model_id": "deepseek-r1-250528",   "provider": "volcengine-ark", "litellm_model": "openai/deepseek-r1-250528",   "in": 0.55, "out": 2.19, "ctx": 131072},
    {"model_id": "deepseek-v3-2-251201", "provider": "volcengine-ark", "litellm_model": "openai/deepseek-v3-2-251201", "in": 0.28, "out": 0.42, "ctx": 131072},
]

# 常见图像模型（litellm 按像素计价、命名带尺寸前缀，这里手工补「每张」价，保证 image 端点有主流模型）
IMAGE_MODELS: list[dict] = [
    {"model_id": "dall-e-3", "provider": "openai", "litellm_model": "openai/dall-e-3", "image_price": 0.04},
    {"model_id": "gpt-image-1", "provider": "openai", "litellm_model": "openai/gpt-image-1", "image_price": 0.04},
]

# 只收录这些模式的模型（chat 为主，后续期再开 embedding / image）
ALLOWED_MODES = {"chat", "embedding", "image_generation"}
# litellm mode → 我们目录的 mode
_MODE_MAP = {"chat": "chat", "embedding": "embedding", "image_generation": "image"}

# 过滤掉日期快照、ft、audio/realtime 等长尾命名，保持目录干净
EXCLUDE_PATTERN = re.compile(
    r"(ft:|audio|realtime|search|transcribe|tts|whisper|davinci|babbage|curie|"
    r"instruct-0914|-\d{4}(-\d{2}){2}|@|latest$)",
    re.IGNORECASE,
)


def _public_name(litellm_key: str) -> str:
    """litellm 键名转对外公开名：去掉 provider/ 前缀"""
    return litellm_key.split("/", 1)[1] if "/" in litellm_key else litellm_key


def _capabilities(info: dict, mode: str) -> list[str]:
    caps = [mode]
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
        litellm_mode = info.get("mode")
        if litellm_mode not in ALLOWED_MODES:
            continue
        mode = _MODE_MAP[litellm_mode]
        provider = LITELLM_PROVIDER_MAP.get(info.get("litellm_provider", ""))
        if provider is None:
            continue
        if EXCLUDE_PATTERN.search(key):
            continue
        # 图像模型只收录：有明确「每张」单价 + 干净模型名（跳过按像素/尺寸前缀的长尾）
        image_price = info.get("output_cost_per_image")
        if mode == "image" and (not image_price or "/" in key):
            continue
        # litellm 价格表里个别 chat 模型被误标 embedding（如 gemini-1.5-flash）；
        # embedding 模型名几乎必含 "embed"，据此过滤掉误标项
        if mode == "embedding" and "embed" not in key.lower():
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
            mode=mode,
            input_price_per_1m=round(in_cost * 1e6, 4) if in_cost else None,
            output_price_per_1m=round(out_cost * 1e6, 4) if out_cost else None,
            image_price=image_price,
            context_window=info.get("max_input_tokens"),
            max_output_tokens=info.get("max_output_tokens"),
            capabilities=_capabilities(info, mode),
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

    # 主流图像模型（手工补每张价）
    for m in IMAGE_MODELS:
        if m["model_id"] in existing:
            continue
        db.add(ModelCatalog(
            model_id=m["model_id"],
            provider_id=provider_ids[m["provider"]],
            litellm_model=m["litellm_model"],
            display_name=m["model_id"],
            mode="image",
            image_price=m["image_price"],
            capabilities=["image"],
            verified=True,
            enabled=True,
        ))
        existing.add(m["model_id"])
        added += 1

    await db.commit()
    return added, len(existing)


async def cleanup_mislabeled(db) -> int:
    """自愈：删除被误标为 embedding 的 chat 模型（名字不含 embed），幂等"""
    from sqlalchemy import delete, func as sqlfunc
    result = await db.execute(
        delete(ModelCatalog).where(
            ModelCatalog.mode == "embedding",
            ~sqlfunc.lower(ModelCatalog.model_id).like("%embed%"),
        )
    )
    await db.commit()
    return result.rowcount or 0


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
        removed = await cleanup_mislabeled(db)
        if removed:
            print(f"cleaned up {removed} mislabeled embedding rows")
        await seed_default_org(db)
        print("default org created & api_keys/usage_records backfilled")


if __name__ == "__main__":
    asyncio.run(main())
