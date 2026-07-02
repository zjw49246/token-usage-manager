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
    max_cost_usd: Optional[float] = Field(None, gt=0)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


class ApiKeyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None
    allowed_models: Optional[list[str]] = None
    max_total_tokens: Optional[int] = Field(None, ge=1)
    max_calls: Optional[int] = Field(None, ge=1)
    max_rpm: Optional[int] = Field(None, ge=1)
    max_cost_usd: Optional[float] = Field(None, gt=0)
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
    max_cost_usd: Optional[float] = None
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
