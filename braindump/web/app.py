"""FastAPI Web application."""

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

from braindump.config import get_config
from braindump.database import init_db

# Frontend SPA build output
FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Simple token-based auth. Active only when secret_key is set in config."""

    def __init__(self, app, secret_key: str):
        super().__init__(app)
        self.secret_key = secret_key

    async def dispatch(self, request: Request, call_next):
        # Allow frontend assets without auth
        if request.url.path.startswith("/assets"):
            return await call_next(request)

        # Check token in query param or cookie
        token = request.query_params.get("token") or request.cookies.get("braindump_token")
        if token != self.secret_key:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        response = await call_next(request)
        # Set cookie so the user doesn't need to pass token on every request
        if request.query_params.get("token") and not request.cookies.get("braindump_token"):
            response.set_cookie("braindump_token", self.secret_key, httponly=True, samesite="lax")
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="braindump", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=500)

    cfg = get_config()

    # Token auth middleware (only if secret_key is configured)
    if cfg.web.secret_key:
        app.add_middleware(TokenAuthMiddleware, secret_key=cfg.web.secret_key)

    # Media files (serve from data dir)
    if cfg.media_dir.exists():
        app.mount("/media", StaticFiles(directory=cfg.media_dir), name="media")

    # API routes (must be before SPA fallback)
    from braindump.web.routes import router
    app.include_router(router)

    # Serve frontend SPA
    if FRONTEND_DIST.exists():
        # Static assets (JS/CSS/fonts)
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")

        # SPA fallback: all unmatched routes return index.html
        @app.get("/{path:path}")
        async def spa_fallback(path: str):
            index_html = FRONTEND_DIST / "index.html"
            return HTMLResponse(index_html.read_text())

    return app


def run_web(host: str | None = None, port: int | None = None):
    cfg = get_config()
    h = host or cfg.web.host
    p = port or cfg.web.port
    app = create_app()
    uvicorn.run(app, host=h, port=p)
