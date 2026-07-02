from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 上游 Gemini 配置
    gemini_use_openai_mode: bool = True
    gemini_openai_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_api_key: str = ""

    # Vertex AI 配置（可选）
    gcp_project_id: str = ""
    gcp_location: str = "global"
    google_application_credentials: str = ""

    # 上游 DeepSeek 配置（可选）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"

    # 管理器配置
    admin_token: str = "change-me"
    # 用户鉴权（P2 多租户）—— 生产务必用 `openssl rand -hex 32` 覆盖
    jwt_secret: str = "change-me-please-set-a-32byte-min-jwt-secret-in-env"
    jwt_access_ttl_minutes: int = 60
    jwt_refresh_ttl_days: int = 30

    # 计费（P4）：新组织赠送的启动额度（USD）；余额 <= 0 时拒绝调用
    welcome_credit_usd: float = 5.0
    enforce_credit_balance: bool = True

    # 路由（P6）：单次请求最多尝试的通道数（首个 + 故障转移）
    max_retries: int = 2

    # 缓存（P7）：相同请求去重复用；命中按 multiplier 折算成本（0=免费）
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300
    cache_hit_cost_multiplier: float = 0.0
    redis_url: str = ""  # 空=进程内内存缓存；填 redis://... 用 Redis（多副本共享）

    # 支付（P9 Stripe）：留空则只支持手动充值
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_currency: str = "usd"
    database_url: str = "sqlite+aiosqlite:///./data/token_manager.db"
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
