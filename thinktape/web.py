"""FastAPI web server."""
from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config
from .core import ThinkTape
from .models import Item

log = logging.getLogger(__name__)


def _item_to_dict(item: Item) -> dict[str, Any]:
    d = item.model_dump(mode="json")
    # frontend wants timestamp strings as-is; pydantic v2 model_dump(json) already does it.
    d["images"] = item.images
    return d


class CreateItemRequest(BaseModel):
    content: str
    type: str = "thought"
    source: str = "web"
    tags: list[str] = []
    bookmark_url: str | None = None


class UpdateItemRequest(BaseModel):
    content: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    summary: str | None = None
    type: str | None = None


def create_app(
    config: Config,
    brain: ThinkTape | None = None,
    summary_worker=None,
) -> FastAPI:
    """Build the FastAPI app. If brain is provided, reuse it (shared with serve mode);
    otherwise create one and manage its lifetime.

    summary_worker (optional) — items created via POST /api/items will be enqueued.
    """

    own_brain = brain is None
    if brain is None:
        brain = ThinkTape(config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if own_brain:
            await brain.connect()
        try:
            yield
        finally:
            if own_brain:
                await brain.close()

    app = FastAPI(title="thinktape", version="2.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------- API ----------

    @app.get("/api/items")
    async def list_items(
        type: str | None = None,
        tag: str | None = None,
        q: str | None = None,
        status: str = "active",
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        if q:
            items = await brain.search(q, limit=limit, offset=offset, status=status)
        else:
            items = await brain.list(
                type=type, tag=tag, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_item_to_dict(i) for i in items],
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/items/{item_id}")
    async def get_item(item_id: str):
        item = await brain.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        return _item_to_dict(item)

    @app.get("/api/items/{item_id}/links")
    async def item_links(item_id: str):
        item = await brain.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        outgoing = await brain.get_links(item_id)
        backlinks = await brain.get_backlinks(item_id)
        return {"outgoing": outgoing, "backlinks": backlinks}

    @app.get("/api/concepts")
    async def list_concepts():
        return {"concepts": await brain.all_concepts()}

    @app.get("/api/concepts/{name}")
    async def concept_detail(name: str):
        items = await brain.get_concept_items(name)
        return {
            "concept": name,
            "items": [_item_to_dict(i) for i in items],
            "total": len(items),
        }

    @app.post("/api/items")
    async def create_item(req: CreateItemRequest):
        item = await brain.add(
            content=req.content,
            type=req.type,
            source=req.source,
            bookmark_url=req.bookmark_url,
            tags=req.tags,
        )
        if summary_worker is not None and item.content.strip():
            summary_worker.enqueue(item.id)
        return _item_to_dict(item)

    @app.patch("/api/items/{item_id}")
    async def update_item(item_id: str, req: UpdateItemRequest):
        changes = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
        item = await brain.update(item_id, **changes)
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        return _item_to_dict(item)

    @app.delete("/api/items/{item_id}")
    async def delete_item(item_id: str):
        ok = await brain.delete(item_id)
        if not ok:
            raise HTTPException(status_code=404, detail="item not found")
        return {"ok": True}

    @app.get("/api/stats")
    async def stats():
        s = await brain.stats()
        return s.model_dump()

    @app.get("/api/tags")
    async def tags():
        return {"tags": await brain.all_tags()}

    @app.post("/api/rebuild-index")
    async def rebuild_index():
        n = await brain.rebuild_index()
        return {"ok": True, "count": n}

    @app.get("/api/items/{item_id}/audio")
    async def item_audio(item_id: str):
        path = brain.store.audio_file(item_id)
        if path is None:
            raise HTTPException(status_code=404, detail="no audio")
        mt, _ = mimetypes.guess_type(path.name)
        return FileResponse(path, media_type=mt or "audio/ogg")

    @app.get("/api/items/{item_id}/video")
    async def item_video(item_id: str):
        path = brain.store.video_file(item_id)
        if path is None:
            raise HTTPException(status_code=404, detail="no video")
        mt, _ = mimetypes.guess_type(path.name)
        return FileResponse(path, media_type=mt or "video/mp4")

    @app.get("/api/items/{item_id}/images/{name}")
    async def item_image(item_id: str, name: str):
        # Path safety: no slashes/parent refs allowed.
        if "/" in name or ".." in name:
            raise HTTPException(status_code=400, detail="invalid name")
        path = brain.store.images_dir(item_id) / name
        if not path.exists():
            raise HTTPException(status_code=404, detail="image not found")
        mt, _ = mimetypes.guess_type(path.name)
        return FileResponse(path, media_type=mt or "image/jpeg")

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}

    # ---------- Static frontend ----------

    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

        @app.get("/")
        async def index():
            return FileResponse(frontend_dist / "index.html")

        @app.get("/favicon.svg")
        async def favicon():
            p = frontend_dist / "favicon.svg"
            if p.exists():
                return FileResponse(p)
            raise HTTPException(status_code=404)

        # SPA fallback for client-side routes
        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            # serve file if it exists in dist root
            candidate = frontend_dist / full_path
            if candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")
    else:
        @app.get("/")
        async def index_placeholder():
            return JSONResponse(
                {
                    "ok": True,
                    "message": "thinktape web — frontend not built yet. Run `cd frontend && npm install && npm run build`.",
                }
            )

    return app
