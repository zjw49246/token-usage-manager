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

    # 路由（P6）：单次请求最多尝试的通道数（首个 + 故障转移）
    max_retries: int = 2
    # 通道健康（P18）：鉴权类错误(401/403)时是否自动禁用通道
    channel_auto_disable: bool = False
    # 定时通道巡检间隔（秒，P28；0=关闭）
    channel_health_check_interval: int = 0
    # 上游调用超时（秒，P20 可配）
    upstream_timeout: int = 600
    # 上游 prompt 缓存读命中的 token 计价折扣（P27，默认 0.25 = 缓存输入按 1/4 价）
    cache_read_price_ratio: float = 0.25
    # 是否把响应里的 reasoning_content 合并进 content（<think> 标签，P29）
    merge_reasoning_content: bool = False

    # 缓存（P7）：相同请求去重复用；命中按 multiplier 折算成本（0=免费）
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300
    cache_hit_cost_multiplier: float = 0.0
    redis_url: str = ""  # 空=进程内内存缓存；填 redis://... 用 Redis（多副本共享）

    # 第三方登录（P11/P24 SSO）：留空则该 provider 不启用
    oauth_github_client_id: str = ""
    oauth_github_client_secret: str = ""
    oauth_google_client_id: str = ""
    oauth_google_client_secret: str = ""
    oauth_discord_client_id: str = ""
    oauth_discord_client_secret: str = ""
    # 通用 OIDC（任意 IdP，通过 issuer 发现端点）
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_display_name: str = "OIDC"
    database_url: str = "sqlite+aiosqlite:///./data/token_manager.db"
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
