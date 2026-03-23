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
    database_url: str = "sqlite+aiosqlite:///./data/token_manager.db"
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
