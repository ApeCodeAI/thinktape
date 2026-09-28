"""Immutable assets plus a read-only adapter for legacy item trees."""
from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
import re
import secrets
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterator

from .models import Asset

# Asia/Shanghai is fixed offset +08:00.
_TZ_CST = timezone(timedelta(hours=8))

_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_SAFE_MEDIA_NAME_RE = re.compile(r"^(?:audio|video)\.[A-Za-z0-9][A-Za-z0-9._-]*$")


class AssetIntegrityError(RuntimeError):
    """An asset no longer matches its immutable SQLite record."""


def _now() -> datetime:
    return datetime.now(_TZ_CST)


def validate_item_id(item_id: str) -> None:
    if not _ID_RE.fullmatch(item_id):
        raise ValueError(f"invalid item id: {item_id!r}")


def _generate_id(now: datetime | None = None) -> str:
    now = now or _now()
    rand = secrets.token_hex(2)
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{rand}"


def _parse_datetime(value) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_TZ_CST)
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError(f"cannot parse datetime: {value!r}")


@dataclass
class StagedAssets:
    item_id: str
    staging_dir: Path | None
    final_dir: Path
    assets: list[Asset]
    promoted: bool = False
    promoted_paths: list[Path] = field(default_factory=list)
    created_final_dir: bool = False


class AssetStore:
    """Immutable filesystem bytes stored below ``data_dir/assets``."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.assets_dir = self.data_dir / "assets"

    async def stage(
        self,
        item_id: str,
        *,
        audio_path: Path | None = None,
        image_paths: list[Path] | None = None,
        video_path: Path | None = None,
        created_at: datetime,
    ) -> StagedAssets:
        task = asyncio.create_task(asyncio.to_thread(
            self._stage_sync,
            item_id,
            audio_path=audio_path,
            image_paths=image_paths or [],
            video_path=video_path,
            created_at=created_at,
        ))
        try:
            return await asyncio.shield(task)
        except BaseException:
            staged = await self._finish_task(task)
            if staged is not None:
                await self.discard(staged)
            raise

    def _stage_sync(
        self,
        item_id: str,
        *,
        audio_path: Path | None,
        image_paths: list[Path],
        video_path: Path | None,
        created_at: datetime,
    ) -> StagedAssets:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self._fsync_dir(self.data_dir)
        final_dir = self.assets_dir / item_id
        sources: list[tuple[str, Path, str]] = []
        if audio_path is not None:
            src = Path(audio_path)
            sources.append(("audio", src, f"audio{src.suffix.lower() or '.bin'}"))
        for index, raw in enumerate(image_paths, start=1):
            src = Path(raw)
            sources.append(("image", src, f"{index:03d}{src.suffix.lower() or '.bin'}"))
        if video_path is not None:
            src = Path(video_path)
            sources.append(("video", src, f"video{src.suffix.lower() or '.bin'}"))
        if not sources:
            return StagedAssets(item_id, None, final_dir, [])

        staging_root = self.assets_dir / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging_dir = staging_root / f"{item_id}-{uuid.uuid4().hex}"
        staging_dir.mkdir()
        assets: list[Asset] = []
        try:
            for kind, src, filename in sources:
                if not src.is_file():
                    raise FileNotFoundError(src)
                dest = staging_dir / filename
                with src.open("rb") as reader, dest.open("xb") as writer:
                    digest = hashlib.sha256()
                    byte_size = 0
                    while chunk := reader.read(1024 * 1024):
                        writer.write(chunk)
                        digest.update(chunk)
                        byte_size += len(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                dest.chmod(0o444)
                mime_type, _ = mimetypes.guess_type(src.name)
                assets.append(Asset(
                    item_id=item_id,
                    path=(Path("assets") / item_id / filename).as_posix(),
                    kind=kind,
                    sha256=digest.hexdigest(),
                    byte_size=byte_size,
                    mime_type=mime_type,
                    original_filename=src.name,
                    created_at=created_at,
                ))
            self._fsync_dir(staging_dir)
            self._fsync_dir(staging_root)
        except BaseException:
            shutil.rmtree(staging_dir, ignore_errors=True)
            self._remove_empty_staging_root()
            raise
        return StagedAssets(item_id, staging_dir, final_dir, assets)

    async def promote(self, staged: StagedAssets) -> None:
        if staged.staging_dir is None:
            return
        await self._run_thread(self._promote_sync, staged)

    def _promote_sync(self, staged: StagedAssets) -> None:
        if staged.final_dir.exists():
            raise FileExistsError(staged.final_dir)
        self._fsync_dir(staged.staging_dir)
        self._fsync_dir(staged.staging_dir.parent)
        staged.staging_dir.replace(staged.final_dir)
        # Mark this before directory fsync: a later fsync failure must still
        # remove the promoted directory when the surrounding DB transaction rolls back.
        staged.promoted = True
        self._fsync_dir(staged.final_dir)
        self._fsync_dir(self.assets_dir)
        self._fsync_dir(self.data_dir)
        self._remove_empty_staging_root()

    async def promote_missing(self, staged: StagedAssets, destinations: set[str]) -> None:
        """Add selected staged files without replacing a pre-existing item directory."""
        await self._run_thread(self._promote_missing_sync, staged, destinations)

    def _promote_missing_sync(self, staged: StagedAssets, destinations: set[str]) -> None:
        if staged.staging_dir is None:
            return
        if not staged.final_dir.exists():
            staged.final_dir.mkdir(parents=True)
            staged.created_final_dir = True
        for asset in staged.assets:
            if asset.path not in destinations:
                continue
            source = staged.staging_dir / Path(asset.path).name
            destination = staged.final_dir / Path(asset.path).name
            if destination.exists():
                raise FileExistsError(destination)
            source.replace(destination)
            staged.promoted_paths.append(destination)
        shutil.rmtree(staged.staging_dir, ignore_errors=True)
        self._remove_empty_staging_root()

    async def discard(self, staged: StagedAssets) -> None:
        await self._run_thread(self._discard_sync, staged)

    def _discard_sync(self, staged: StagedAssets) -> None:
        if staged.promoted:
            shutil.rmtree(staged.final_dir, ignore_errors=True)
        else:
            for path in staged.promoted_paths:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            if staged.staging_dir is not None:
                shutil.rmtree(staged.staging_dir, ignore_errors=True)
            if staged.created_final_dir:
                try:
                    staged.final_dir.rmdir()
                except OSError:
                    pass
        self._remove_empty_staging_root()

    async def _run_thread(self, func, *args):
        task = asyncio.create_task(asyncio.to_thread(func, *args))
        try:
            return await asyncio.shield(task)
        except BaseException:
            await self._finish_task(task)
            raise

    @staticmethod
    async def _finish_task(task: asyncio.Task):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        return task.result()

    def path_for(self, asset: Asset) -> Path:
        validate_item_id(asset.item_id)
        expected_parent = Path("assets") / asset.item_id
        relative = Path(asset.path)
        if relative.is_absolute() or relative.parent != expected_parent or relative.name in {"", ".", ".."}:
            raise ValueError(f"invalid asset path: {asset.path}")
        path = (self.data_dir / relative).resolve()
        root = self.assets_dir.resolve()
        expected_dir = (self.assets_dir / asset.item_id).resolve()
        if path.parent != expected_dir or root not in path.parents:
            raise ValueError(f"invalid asset path: {asset.path}")
        return path

    async def verified_path(self, asset: Asset) -> Path:
        path = self.path_for(asset)
        if path.is_symlink() or not path.is_file():
            raise AssetIntegrityError("asset integrity check failed")
        digest, byte_size = await asyncio.to_thread(self._digest_file, path)
        if digest != asset.sha256 or byte_size != asset.byte_size:
            raise AssetIntegrityError("asset integrity check failed")
        return path

    async def make_read_only(self, asset: Asset) -> None:
        path = self.path_for(asset)
        await asyncio.to_thread(path.chmod, 0o444)

    @staticmethod
    def _digest_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        byte_size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                byte_size += len(chunk)
        return digest.hexdigest(), byte_size

    @staticmethod
    def _fsync_dir(path: Path | None) -> None:
        if path is None:
            return
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        fd = os.open(path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _remove_empty_staging_root(self) -> None:
        root = self.assets_dir / ".staging"
        try:
            root.rmdir()
        except OSError:
            pass


class ItemStore:
    """Read-only adapter for legacy ``items/<id>`` directories."""

    def __init__(self, items_dir: Path):
        self.items_dir = Path(items_dir)

    # ---------- path helpers ----------

    def item_dir(self, item_id: str) -> Path:
        return self.items_dir / item_id

    def yaml_path(self, item_id: str) -> Path:
        return self.item_dir(item_id) / "item.yaml"

    def content_path(self, item_id: str) -> Path:
        return self.item_dir(item_id) / "content.md"

    def audio_path(self, item_id: str) -> Path:
        # Default container; consumers should glob for audio.* if extension may vary.
        return self.item_dir(item_id) / "audio.opus"

    def video_path(self, item_id: str) -> Path:
        return self.item_dir(item_id) / "video.mp4"

    def images_dir(self, item_id: str) -> Path:
        return self.item_dir(item_id) / "images"

    def audio_file(self, item_id: str) -> Path | None:
        files = self.audio_files(item_id)
        return files[0] if len(files) == 1 else None

    def audio_files(self, item_id: str) -> list[Path]:
        return self._named_media_files(item_id, "audio")

    def video_file(self, item_id: str) -> Path | None:
        files = self.video_files(item_id)
        return files[0] if len(files) == 1 else None

    def video_files(self, item_id: str) -> list[Path]:
        return self._named_media_files(item_id, "video")

    def _named_media_files(self, item_id: str, stem: str) -> list[Path]:
        item_dir = self.item_dir(item_id)
        if not item_dir.is_dir():
            return []
        return sorted(
            path for path in item_dir.iterdir()
            if path.name.startswith(f"{stem}.")
            and _SAFE_MEDIA_NAME_RE.fullmatch(path.name)
            and path.is_file()
        )

    def image_files(self, item_id: str) -> list[Path]:
        d = self.images_dir(item_id)
        if not d.exists():
            return []
        return sorted(p for p in d.iterdir() if p.is_file() and not p.name.startswith("."))

    # ---------- legacy discovery ----------

    def iter_ids(self) -> Iterator[str]:
        if not self.items_dir.exists():
            return
        for p in sorted(self.items_dir.iterdir()):
            if p.is_dir() and _ID_RE.match(p.name):
                yield p.name

def generate_id(now: datetime | None = None) -> str:
    """Exposed for tests."""
    return _generate_id(now)
