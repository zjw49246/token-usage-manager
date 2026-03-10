from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings
import os

# 确保 data 目录存在
os.makedirs("data", exist_ok=True)

engine = create_async_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """建表"""
    from app import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 开启 WAL 模式提升并发写性能
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
