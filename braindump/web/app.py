"""FastAPI Web application."""

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware

from braindump.config import get_config
from braindump.database import init_db

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="braindump", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # Static files
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # Media files (serve from data dir)
    cfg = get_config()
    if cfg.media_dir.exists():
        app.mount("/media", StaticFiles(directory=cfg.media_dir), name="media")

    # Routes
    from braindump.web.routes import router
    app.include_router(router)

    return app


def run_web(host: str | None = None, port: int | None = None):
    cfg = get_config()
    h = host or cfg.web.host
    p = port or cfg.web.port
    app = create_app()
    uvicorn.run(app, host=h, port=p)
