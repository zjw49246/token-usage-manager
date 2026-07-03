from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── API Key ──────────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    allowed_models: Optional[list[str]] = None
    max_total_tokens: Optional[int] = Field(None, ge=1)
    max_calls: Optional[int] = Field(None, ge=1)
    max_rpm: Optional[int] = Field(None, ge=1)
    model_rpm: Optional[dict] = None
    max_cost_usd: Optional[float] = Field(None, gt=0)
    allowed_ips: Optional[list[str]] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


class ApiKeyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None
    allowed_models: Optional[list[str]] = None
    max_total_tokens: Optional[int] = Field(None, ge=1)
    max_calls: Optional[int] = Field(None, ge=1)
    max_rpm: Optional[int] = Field(None, ge=1)
    model_rpm: Optional[dict] = None
    max_cost_usd: Optional[float] = Field(None, gt=0)
    allowed_ips: Optional[list[str]] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


class UsageSummaryOut(BaseModel):
    total_tokens_used: int
    total_calls: int
    total_cost_usd: float = 0.0
    last_call_at: Optional[datetime]


class ApiKeyOut(BaseModel):
    id: int
    key_prefix: str
    name: str
    is_active: bool
    allowed_models: Optional[list[str]]
    max_total_tokens: Optional[int]
    max_calls: Optional[int]
    max_rpm: Optional[int]
    model_rpm: Optional[dict] = None
    max_cost_usd: Optional[float] = None
    allowed_ips: Optional[list[str]] = None
    valid_from: Optional[datetime]
    valid_until: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    usage: Optional[UsageSummaryOut] = None

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyOut):
    """创建时额外返回明文 key（仅此一次）"""
    key: str


# ── Usage ────────────────────────────────────────────────────────────────────

class UsageRecordOut(BaseModel):
    id: int
    api_key_id: int
    model: str
    provider: Optional[str] = None
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    cost_usd: Optional[float] = None
    cached: bool = False
    cached_tokens: Optional[int] = None
    duration_ms: Optional[int]
    status: str
    error_message: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class UsageListOut(BaseModel):
    items: list[UsageRecordOut]
    total: int
    page: int
    page_size: int


# ── Stats ────────────────────────────────────────────────────────────────────

class OverviewStats(BaseModel):
    total_tokens: int
    today_tokens: int
    active_keys: int
    total_keys: int
    today_calls: int
    total_calls: int
    total_cost_usd: float = 0.0
    today_cost_usd: float = 0.0


class TrendPoint(BaseModel):
    time: str
    tokens: int
    calls: int


class TrendStats(BaseModel):
    points: list[TrendPoint]


class KeyTokenShare(BaseModel):
    name: str
    key_prefix: str
    tokens: int


# ── 用户与组织（P2 多租户）───────────────────────────────────────────────────

class RegisterIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=100)


class LoginIn(BaseModel):
    email: str
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


class OAuthExchangeIn(BaseModel):
    code: str
    redirect_uri: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    is_superadmin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class OrgOut(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime
    role: Optional[str] = None  # 当前用户在该组织的角色

    model_config = {"from_attributes": True}


class MemberAdd(BaseModel):
    email: str
    role: str = Field("member", pattern="^(member|admin|owner)$")
    budget_usd: Optional[float] = Field(None, gt=0)


class MemberUpdate(BaseModel):
    role: Optional[str] = Field(None, pattern="^(member|admin|owner)$")
    budget_usd: Optional[float] = Field(None, ge=0)  # 0 或 null 视为不限


class MemberOut(BaseModel):
    id: int
    user_id: int
    email: str
    name: str
    role: str
    budget_usd: Optional[float] = None
    created_at: datetime


class PlaygroundIn(BaseModel):
    model: str
    messages: list[dict]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = Field(None, ge=1)


# ── 上游通道（P6 负载均衡/故障转移）─────────────────────────────────────────────

class ChannelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider_id: int
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    models: Optional[list[str]] = None
    model_map: Optional[dict] = None
    weight: int = Field(1, ge=1)
    priority: int = Field(0)
    enabled: bool = True


class ChannelUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    models: Optional[list[str]] = None
    model_map: Optional[dict] = None
    weight: Optional[int] = Field(None, ge=1)
    priority: Optional[int] = None
    enabled: Optional[bool] = None
    status: Optional[str] = None


class ChannelOut(BaseModel):
    id: int
    name: str
    provider_id: int
    api_base: Optional[str]
    models: Optional[list[str]]
    model_map: Optional[dict]
    weight: int
    priority: int
    enabled: bool
    status: str
    success_count: int = 0
    error_count: int = 0
    success_rate: Optional[float] = None
    created_at: datetime
    has_key: bool = False  # 是否配了独立凭证（不回显明文）

    model_config = {"from_attributes": True}
