from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_admin import load_database_pool_settings_from_store, router as admin_router
from app.api.routes_auth import router as auth_router
from app.api.routes_creative import router as creative_router
from app.api.routes_exports import router as exports_router
from app.api.routes_ingest import router as ingest_router
from app.api.routes_link_records import router as link_records_router
from app.api.routes_products import router as products_router
from app.api.routes_sourcing_1688 import router as sourcing_1688_router
from app.api.routes_sync import router as sync_router
from app.api.routes_upload import router as upload_router
from app.api.routes_visual_generation import router as visual_generation_router
from app.core.config import cloud_database_enabled, ensure_runtime_dirs
from app.core.database import init_db
from app.core.postgres_pool import close_all_postgres_pools


def create_app() -> FastAPI:
    ensure_runtime_dirs()
    if not cloud_database_enabled():
        init_db()

    app = FastAPI(title="Temu 选品上架工作台 API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_origin_regex=r"^(http://(localhost|127\.0\.0\.1):\d+|chrome-extension://[a-z]+)$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        max_age=86400,
    )

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(upload_router)
    app.include_router(ingest_router)
    app.include_router(products_router)
    app.include_router(sourcing_1688_router)
    app.include_router(exports_router)
    app.include_router(link_records_router)
    app.include_router(creative_router)
    app.include_router(sync_router)
    app.include_router(visual_generation_router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.on_event("startup")
    def load_postgres_pool_settings():
        load_database_pool_settings_from_store()

    @app.on_event("shutdown")
    def close_postgres_pools():
        close_all_postgres_pools()

    return app


app = create_app()
