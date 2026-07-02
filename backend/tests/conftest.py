import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.main import app
from app.database import Base, get_db
from app.config import settings

# 覆盖 admin token 方便测试
settings.admin_token = "test-admin-token"

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)

# 后台记账 task 直接用 services.router.AsyncSessionLocal（不走 get_db 依赖注入），
# 测试时必须重定向到测试库，否则会写进真实数据库文件
import app.services.router as _router_service  # noqa: E402
_router_service.AsyncSessionLocal = TestSessionLocal


async def _seed_minimal_catalog():
    """测试用最小模型目录：入口现在是目录驱动的（P1），无目录则无模型"""
    from app.models import Provider, ModelCatalog

    async with TestSessionLocal() as db:
        google = Provider(name="google", litellm_prefix="gemini", credential_env="GEMINI_API_KEY")
        ark = Provider(
            name="volcengine-ark", litellm_prefix="openai",
            api_base="https://ark.example.com/api/v3", credential_env="DEEPSEEK_API_KEY",
        )
        db.add_all([google, ark])
        await db.flush()
        db.add_all([
            ModelCatalog(
                model_id="gemini-2.0-flash", provider_id=google.id,
                litellm_model="gemini/gemini-2.0-flash",
                input_price_per_1m=0.1, output_price_per_1m=0.4, context_window=1048576,
            ),
            ModelCatalog(
                model_id="gemini-2.5-pro", provider_id=google.id,
                litellm_model="gemini/gemini-2.5-pro",
                input_price_per_1m=1.25, output_price_per_1m=10.0, context_window=1048576,
            ),
            ModelCatalog(
                model_id="deepseek-v3-250324", provider_id=ark.id,
                litellm_model="openai/deepseek-v3-250324",
                input_price_per_1m=0.28, output_price_per_1m=0.42, context_window=131072,
            ),
            ModelCatalog(
                model_id="text-embedding-3-small", provider_id=google.id,
                litellm_model="openai/text-embedding-3-small", mode="embedding",
                input_price_per_1m=0.02, capabilities=["embedding"],
            ),
            ModelCatalog(
                model_id="dall-e-3", provider_id=google.id,
                litellm_model="openai/dall-e-3", mode="image",
                image_price=0.04, capabilities=["image"],
            ),
            ModelCatalog(
                model_id="rerank-v3.5", provider_id=google.id,
                litellm_model="cohere/rerank-v3.5", mode="rerank", capabilities=["rerank"],
            ),
            ModelCatalog(
                model_id="gpt-5-responses", provider_id=google.id,
                litellm_model="openai/gpt-5-responses", mode="chat", capabilities=["chat"],
            ),
        ])
        await db.commit()


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    from app.services.cache import reset_cache
    reset_cache()  # 每个测试用全新缓存，避免相同请求跨测试命中
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_minimal_catalog()
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def admin_client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer test-admin-token"},
    ) as c:
        yield c
