from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.db import init_db


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(router, prefix="/api")

    @app.on_event("startup")
    def on_startup() -> None:
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        settings.fixture_dir.mkdir(parents=True, exist_ok=True)
        init_db()

    return app


app = create_app()
