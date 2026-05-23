from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_products import router as products_router
from app.api.routes_sourcing_1688 import router as sourcing_1688_router
from app.api.routes_upload import router as upload_router
from app.core.config import ensure_runtime_dirs
from app.core.database import init_db


def create_app() -> FastAPI:
    ensure_runtime_dirs()
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
    )

    app.include_router(upload_router)
    app.include_router(products_router)
    app.include_router(sourcing_1688_router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app


app = create_app()
