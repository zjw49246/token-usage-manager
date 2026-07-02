from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import admin, proxy, auth, orgs, catalog, ingress_anthropic, ingress_gemini


async def _seed_if_empty():
    """容器/首次启动时，若模型目录为空则自动 seed（幂等），保证开箱即用"""
    from sqlalchemy import select, func
    from app.database import AsyncSessionLocal
    from app.models import ModelCatalog
    from scripts.seed import seed_providers, seed_catalog, seed_default_org

    async with AsyncSessionLocal() as db:
        count = await db.scalar(select(func.count()).select_from(ModelCatalog))
        if count and count > 0:
            return
        provider_ids = await seed_providers(db)
        await seed_catalog(db, provider_ids)
        await seed_default_org(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _seed_if_empty()
    yield


app = FastAPI(
    title="TokenRouter",
    version="1.0.0",
    lifespan=lifespan,
    # 生产环境可关闭 docs
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(orgs.router)
app.include_router(catalog.router)
app.include_router(admin.router)
app.include_router(proxy.router)
app.include_router(ingress_anthropic.router)
app.include_router(ingress_gemini.router)

# 挂载前端静态文件（build 后）
_frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve index.html for all non-API routes (SPA fallback)."""
        file_path = _frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_frontend_dist / "index.html"))
