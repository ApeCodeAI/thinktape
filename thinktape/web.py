"""FastAPI web server."""
from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import KEY_HEADER, DeviceKeyStore, is_loopback
from .config import Config
from .core import AssetIntegrityError, ThinkTape
from .models import Item

log = logging.getLogger(__name__)


def _item_to_dict(item: Item) -> dict[str, Any]:
    d = item.model_dump(mode="json")
    # frontend wants timestamp strings as-is; pydantic v2 model_dump(json) already does it.
    # Expose the union of explicit tags + inline #hashtags so every response
    # (including store-sourced GET) shows hashtags typed into the body.
    d["tags"] = item.all_tags
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


class PairRequest(BaseModel):
    name: str = "device"


def create_app(
    config: Config,
    brain: ThinkTape | None = None,
    summary_worker=None,
    transcribe_queue=None,
) -> FastAPI:
    """Build the FastAPI app. If brain is provided, reuse it (shared with serve mode);
    otherwise create one and manage its lifetime.

    summary_worker (optional) — items created via POST /api/items will be enqueued.
    transcribe_queue (optional) — uploaded audio/video will be queued for transcription.
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

    key_store = DeviceKeyStore(config.data_dir)

    async def _device_key_auth(request: Request, call_next):
        # Local machine is always trusted. Remote clients need a paired key
        # only once at least one device exists — so existing setups are unaffected.
        if request.url.path.startswith("/api/"):
            client_host = request.client.host if request.client else None
            if not is_loopback(client_host) and not key_store.is_empty():
                if not key_store.verify(request.headers.get(KEY_HEADER)):
                    return JSONResponse({"detail": "unauthorized device"}, status_code=401)
        return await call_next(request)

    # Auth added first (inner); CORS added last (outer) so 401s keep CORS headers.
    app.add_middleware(BaseHTTPMiddleware, dispatch=_device_key_auth)
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

    @app.post("/api/items/upload")
    async def upload_item(
        content: str = Form(""),
        type: str = Form("thought"),
        tags: str = Form(""),
        audio: UploadFile | None = File(None),
        images: list[UploadFile] | None = File(None),
        video: UploadFile | None = File(None),
    ):
        """Create an item from uploaded media (voice memo, photos, video)."""
        tmpdir = Path(tempfile.mkdtemp(prefix="tt-upload-"))

        def _ext(filename: str | None, default: str) -> str:
            return os.path.splitext(filename or "")[1] or default

        def _save(uf: UploadFile, name: str) -> Path:
            dest = tmpdir / name
            with dest.open("wb") as f:
                shutil.copyfileobj(uf.file, f)
            return dest

        try:
            audio_path = _save(audio, "audio" + _ext(audio.filename, ".m4a")) if audio else None
            video_path = _save(video, "video" + _ext(video.filename, ".mp4")) if video else None
            image_paths: list[Path] = []
            for i, img in enumerate(images or [], start=1):
                image_paths.append(_save(img, f"image-{i}" + _ext(img.filename, ".jpg")))

            tag_list = [
                t.strip().lstrip("#")
                for t in (tags or "").replace("，", ",").split(",")
                if t.strip()
            ]
            item_type = type if type in ("thought", "bookmark", "note") else "thought"
            body = content or ""
            # Voice memo with no text yet → placeholder + queue transcription.
            if audio_path is not None and not body.strip() and transcribe_queue is not None:
                body = "[转写中…]"

            item = await brain.add(
                content=body,
                type=item_type,
                source="app",
                audio_path=audio_path,
                image_paths=image_paths or None,
                video_path=video_path,
                tags=tag_list or None,
            )
            if audio_path is not None and transcribe_queue is not None:
                transcribe_queue.enqueue(item.id)
            if (
                summary_worker is not None
                and item.content.strip()
                and not item.content.startswith("[转写")
            ):
                summary_worker.enqueue(item.id)
            return _item_to_dict(item)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

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

    @app.get("/api/devices")
    async def list_devices():
        return {"devices": key_store.list_public(), "auth_active": not key_store.is_empty()}

    @app.post("/api/pair")
    async def pair_device(req: PairRequest):
        entry = key_store.add(req.name)
        return {"name": entry["name"], "key": entry["key"]}

    @app.post("/api/rebuild-index")
    async def rebuild_index():
        n = await brain.rebuild_index()
        return {"ok": True, "count": n}

    @app.get("/api/items/{item_id}/audio")
    async def item_audio(item_id: str):
        try:
            path = await brain.media_file(item_id, "audio")
        except AssetIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if path is None:
            raise HTTPException(status_code=404, detail="no audio")
        mt, _ = mimetypes.guess_type(path.name)
        return FileResponse(path, media_type=mt or "audio/ogg")

    @app.get("/api/items/{item_id}/video")
    async def item_video(item_id: str):
        try:
            path = await brain.media_file(item_id, "video")
        except AssetIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if path is None:
            raise HTTPException(status_code=404, detail="no video")
        mt, _ = mimetypes.guess_type(path.name)
        return FileResponse(path, media_type=mt or "video/mp4")

    @app.get("/api/items/{item_id}/images/{name}")
    async def item_image(item_id: str, name: str):
        # Path safety: no slashes/parent refs allowed.
        if "/" in name or ".." in name:
            raise HTTPException(status_code=400, detail="invalid name")
        try:
            path = await brain.image_file(item_id, name)
        except AssetIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if path is None:
            raise HTTPException(status_code=404, detail="image not found")
        mt, _ = mimetypes.guess_type(path.name)
        return FileResponse(path, media_type=mt or "image/jpeg")

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}

    # ---------- Static frontend ----------
    # Prefer the new Expo universal web build; fall back to the legacy Vite web.
    repo_root = Path(__file__).resolve().parent.parent
    web_dist = repo_root / "app" / "dist"
    if not (web_dist / "index.html").exists():
        web_dist = repo_root / "frontend" / "dist"
    web_dist = web_dist.resolve()
    index_file = web_dist / "index.html"

    if index_file.exists():

        @app.get("/")
        async def index():
            return FileResponse(index_file)

        # Serve any built static asset; fall back to index.html for client routes.
        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (web_dist / full_path).resolve()
            # Path-traversal guard: candidate must stay within web_dist.
            if web_dist == candidate or web_dist in candidate.parents:
                if candidate.is_file():
                    return FileResponse(candidate)
                html = (web_dist / f"{full_path}.html").resolve()
                if html.is_file() and web_dist in html.parents:
                    return FileResponse(html)
            return FileResponse(index_file)
    else:
        @app.get("/")
        async def index_placeholder():
            return JSONResponse(
                {
                    "ok": True,
                    "message": "thinktape web — frontend not built yet. Run `cd app && npx expo export -p web` (or build the legacy frontend).",
                }
            )

    return app
