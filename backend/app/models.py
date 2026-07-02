from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Boolean, BigInteger, Integer, Float, DateTime, Text, JSON,
    ForeignKey, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


# ══════════════════ 多租户（SaaS）══════════════════


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    credit_balance_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="organization", lazy="noload")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", lazy="noload")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")  # owner / admin / member
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="memberships", lazy="noload")
    user: Mapped["User"] = relationship(back_populates="memberships", lazy="noload")


class CreditTransaction(Base):
    """组织级计费流水台账：充值(+)、消费(-)、调整(±)"""
    __tablename__ = "credit_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # topup / usage / adjustment
    ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 关联的 usage_record id 等
    balance_after: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, index=True)


# ══════════════════ 供应商与模型目录（平台级）══════════════════


class Provider(Base):
    """上游供应商注册表：替代硬编码的 if/else 路由分支"""
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)  # openai / anthropic / google / deepseek …
    litellm_prefix: Mapped[str] = mapped_column(String(50), nullable=False)  # 传给 LiteLLM 的前缀
    api_base: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 自定义 base URL；null = LiteLLM 默认
    credential_env: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 凭证 env 变量名
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    models: Mapped[list["ModelCatalog"]] = relationship(back_populates="provider", lazy="noload")


class ModelCatalog(Base):
    """模型目录 + 价格：对比页与成本核算的数据源（seed 自 litellm.model_cost）"""
    __tablename__ = "model_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)  # 对外公开名
    provider_id: Mapped[int] = mapped_column(Integer, ForeignKey("providers.id"), nullable=False, index=True)
    litellm_model: Mapped[str] = mapped_column(String(200), nullable=False)  # 传给 LiteLLM 的全名
    display_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    input_price_per_1m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # USD / 1M tokens
    output_price_per_1m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # USD / 1M tokens
    context_window: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    capabilities: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # ["chat","vision","tools",…]
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    provider: Mapped["Provider"] = relationship(back_populates="models", lazy="noload")


class Channel(Base):
    """上游通道（P6）：一个模型可由多条通道服务，支持加权负载均衡 + 失败故障转移。

    每条通道 = 具体上游路由（供应商 + 凭证 + api_base + 服务的模型集）。
    路由时：找出服务该模型的启用通道 → 按 priority 分层、层内按 weight 加权随机 → 逐条重试。
    """
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_id: Mapped[int] = mapped_column(Integer, ForeignKey("providers.id"), nullable=False, index=True)
    api_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 上游凭证；空=回退 provider.credential_env
    api_base: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 覆盖；空=用 provider.api_base
    models: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)      # 本通道服务的公开 model_id 列表
    model_map: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)   # {公开名: 上游 litellm 全名} 覆盖
    weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)       # 加权随机权重
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)     # 优先级，高者先试
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active / error / disabled
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    provider: Mapped["Provider"] = relationship(lazy="noload")


# ══════════════════ API Key 与用量（租户级）══════════════════


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 多租户归属（P0 期间可空，P2 强制）
    org_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    # 权限控制
    allowed_models: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # null = 不限
    max_total_tokens: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # null = 不限
    max_calls: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)           # null = 不限
    max_rpm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)             # null = 不限
    max_cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)        # null = 不限（USD 限额）
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)    # null = 不限
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)   # null = 不限

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    usage_records: Mapped[list["UsageRecord"]] = relationship(back_populates="api_key", lazy="noload")
    usage_summary: Mapped[Optional["UsageSummary"]] = relationship(back_populates="api_key", uselist=False, lazy="noload")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=False, index=True)
    org_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)  # 反范式，租户查询提速
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 按目录单价核算
    cached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")  # 是否缓存命中
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, index=True)

    api_key: Mapped["ApiKey"] = relationship(back_populates="usage_records", lazy="noload")


class UsageSummary(Base):
    __tablename__ = "usage_summary"

    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), primary_key=True)
    total_tokens_used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, server_default="0")
    last_call_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    api_key: Mapped["ApiKey"] = relationship(back_populates="usage_summary", lazy="noload")
