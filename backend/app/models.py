from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, BigInteger, Integer, DateTime, Text, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 权限控制
    allowed_models: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # null = 不限
    max_total_tokens: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # null = 不限
    max_calls: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)           # null = 不限
    max_rpm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)             # null = 不限
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
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
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
    last_call_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    api_key: Mapped["ApiKey"] = relationship(back_populates="usage_summary", lazy="noload")
