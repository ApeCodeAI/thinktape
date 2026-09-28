"""Explicit read-only migration from the retired YAML/Markdown layout."""
from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from .models import Asset, Item
from .store import _parse_datetime

if TYPE_CHECKING:
    from .core import ThinkTape


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _same_item(canonical: Item, legacy: Item) -> bool:
    fields = (
        "id", "created_at", "updated_at", "type", "source", "status",
        "bookmark_url", "summary", "telegram_message_id", "content",
    )
    if not all(getattr(canonical, field) == getattr(legacy, field) for field in fields):
        return False
    # The retired index persisted explicit tags unioned with inline hashtags.
    # Accept only that exact historical representation; every other metadata
    # field above remains an exact comparison and the canonical row is untouched.
    return canonical.tags == legacy.tags or canonical.tags == legacy.all_tags


def _same_assets(left: list[Asset], right: list[Asset]) -> bool:
    fields = (
        "item_id", "path", "kind", "sha256", "byte_size", "mime_type",
        "original_filename", "created_at",
    )
    key = lambda asset: tuple(getattr(asset, field) for field in fields)
    return sorted(map(key, left)) == sorted(map(key, right))


def _asset_signature(asset: Asset) -> tuple:
    return (
        asset.item_id, asset.path, asset.kind, asset.sha256, asset.byte_size,
        asset.mime_type, asset.original_filename, asset.created_at,
    )


def _media_flags(item: Item) -> tuple[bool, bool, bool]:
    return item.has_audio, item.has_images, item.has_video


class LegacyMigrator:
    """Import legacy items without modifying their source tree."""

    def __init__(self, brain: ThinkTape):
        self.brain = brain
        self.legacy = brain.store

    async def run(
        self, *, dry_run: bool = True, verify_preexisting: bool = False,
    ) -> dict[str, Any]:
        preexisting_ids = (
            set(await self.brain.index.item_ids()) if verify_preexisting else set()
        )
        valid_preexisting_ids: set[str] = set()
        report: dict[str, Any] = {
            "mode": "dry-run" if dry_run else "apply",
            "source": str(self.legacy.items_dir),
            "canonical_database": str(self.brain.config.db_path),
            "asset_root": str(self.brain.config.assets_dir),
            "counts": {
                "scanned": 0,
                "ready": 0,
                "imported": 0,
                "updated": 0,
                "skipped": 0,
                "assets_found": 0,
                "assets_imported": 0,
                "verified_files": 0,
                "issues": 0,
            },
            "items": [],
            "issues": [],
        }
        for item_id in self.legacy.iter_ids():
            report["counts"]["scanned"] += 1
            try:
                result = await self._inspect_item(item_id)
            except Exception as exc:
                self._issue(
                    report, item_id,
                    getattr(exc, "code", "invalid_legacy_item"), str(exc),
                )
                continue

            report["counts"]["assets_found"] += len(result["assets"])
            existing = await self.brain.index.get(item_id)
            existing_assets = await self.brain.list_assets(item_id)
            if existing is not None and not _same_item(existing, result["item"]):
                self._issue(
                    report,
                    item_id,
                    "item_conflict",
                    "existing canonical SQLite item differs from legacy content or metadata",
                )
                continue
            if (
                existing is not None
                and item_id in preexisting_ids
                and _media_flags(existing) != _media_flags(result["item"])
            ):
                self._issue(
                    report,
                    item_id,
                    "media_flag_mismatch",
                    "pre-existing SQLite media flags do not match legacy asset records",
                )
                continue
            issue = self._validate_destination(result["assets"], existing_assets)
            if issue is not None:
                self._issue(report, item_id, issue["code"], issue["message"], issue.get("path"))
                continue
            if existing is not None and item_id in preexisting_ids:
                valid_preexisting_ids.add(item_id)

            item_changed = existing is None
            assets_changed = not _same_assets(existing_assets, result["assets"])
            action = (
                "would-import" if dry_run and existing is None
                else "would-update" if dry_run and (item_changed or assets_changed)
                else "imported" if existing is None
                else "updated" if item_changed or assets_changed
                else "skipped"
            )
            report["counts"]["ready"] += 1
            entry = {
                "id": item_id,
                "action": action,
                "assets": len(result["assets"]),
                "checksums": result["checksums"],
            }
            report["items"].append(entry)

            if dry_run:
                report["counts"]["verified_files"] += result["verified_files"]
                continue

            try:
                copied = await self._apply_item(
                    result["item"], result["asset_sources"], result["assets"],
                    existing_assets, result["source_hashes"], insert_item=existing is None,
                )
            except Exception as exc:
                self._issue(report, item_id, "import_failed", str(exc))
                entry["action"] = "failed"
                continue

            if existing is None:
                report["counts"]["imported"] += 1
            elif item_changed or assets_changed:
                report["counts"]["updated"] += 1
            else:
                report["counts"]["skipped"] += 1
            report["counts"]["assets_imported"] += copied
            report["counts"]["verified_files"] += result["verified_files"]

        issue_ids = {issue["item_id"] for issue in report["issues"]}
        for item_id in sorted(preexisting_ids - valid_preexisting_ids - issue_ids):
            self._issue(
                report,
                item_id,
                "missing_legacy_item",
                "pre-existing SQLite item has no valid matching legacy item",
            )
        report["counts"]["issues"] = len(report["issues"])
        report["ok"] = not report["issues"]
        return report

    async def _inspect_item(self, item_id: str) -> dict[str, Any]:
        item_dir = self.legacy.item_dir(item_id)
        metadata_path = self.legacy.yaml_path(item_id)
        content_path = self.legacy.content_path(item_id)
        self._validate_item_dir(item_dir)
        if metadata_path.exists() or metadata_path.is_symlink():
            self._validate_input_path(metadata_path, item_dir)
        if content_path.exists() or content_path.is_symlink():
            self._validate_input_path(content_path, item_dir)
        if not metadata_path.is_file():
            raise ValueError("missing item.yaml")
        if not content_path.is_file():
            error = ValueError("missing content.md")
            error.code = "missing_legacy_content"  # type: ignore[attr-defined]
            raise error

        source_paths = [metadata_path]
        metadata_bytes = await asyncio.to_thread(metadata_path.read_bytes)
        data = yaml.safe_load(metadata_bytes) or {}
        metadata_id = str(data.get("id", item_id))
        if metadata_id != item_id:
            error = ValueError(f"item.yaml id {metadata_id!r} does not match directory {item_id!r}")
            error.code = "item_id_mismatch"  # type: ignore[attr-defined]
            raise error

        source_paths.append(content_path)
        content = (await asyncio.to_thread(content_path.read_bytes)).decode("utf-8")

        audio_files = self.legacy.audio_files(item_id)
        video_files = self.legacy.video_files(item_id)
        images_dir = self.legacy.images_dir(item_id)
        if images_dir.exists() or images_dir.is_symlink():
            self._validate_input_path(images_dir, item_dir)
        image_files = self.legacy.image_files(item_id)
        for path in (*audio_files, *video_files, *image_files):
            self._validate_input_path(path, item_dir)
        self._validate_expected_media(item_id, data, audio_files, video_files, image_files)

        media: list[tuple[str, Path, str]] = []
        audio = audio_files[0] if audio_files else None
        if audio is not None:
            media.append(("audio", audio, f"audio{audio.suffix.lower() or '.bin'}"))
        for index, image in enumerate(image_files, start=1):
            media.append(("image", image, f"{index:03d}{image.suffix.lower() or '.bin'}"))
        video = video_files[0] if video_files else None
        if video is not None:
            media.append(("video", video, f"video{video.suffix.lower() or '.bin'}"))
        source_paths.extend(source for _, source, _ in media)

        source_hashes = {path: await asyncio.to_thread(_sha256, path) for path in source_paths}
        created_at = _parse_datetime(data["created_at"])
        updated_at = _parse_datetime(data.get("updated_at", data["created_at"]))
        item = Item(
            id=item_id,
            created_at=created_at,
            updated_at=updated_at,
            type=data.get("type", "thought"),
            source=data.get("source", "telegram"),
            tags=list(data.get("tags") or []),
            status=data.get("status", "active"),
            bookmark_url=data.get("bookmark_url"),
            summary=data.get("summary"),
            telegram_message_id=data.get("telegram_message_id"),
            has_audio=any(kind == "audio" for kind, _, _ in media),
            has_images=any(kind == "image" for kind, _, _ in media),
            has_video=any(kind == "video" for kind, _, _ in media),
            content=content,
            images=[name for kind, _, name in media if kind == "image"],
        )
        assets = [
            Asset(
                item_id=item_id,
                path=(Path("assets") / item_id / destination).as_posix(),
                kind=kind,
                sha256=source_hashes[source],
                byte_size=source.stat().st_size,
                mime_type=mimetypes.guess_type(source.name)[0],
                original_filename=source.name,
                created_at=created_at,
            )
            for kind, source, destination in media
        ]
        checksums = {
            "metadata": source_hashes[metadata_path],
            "content": source_hashes.get(content_path),
            "media": {
                source.relative_to(item_dir).as_posix(): source_hashes[source]
                for _, source, _ in media
            },
        }
        await self._verify_source_hashes(source_hashes)
        return {
            "item": item,
            "assets": assets,
            "asset_sources": {asset.path: source for asset, (_, source, _) in zip(assets, media)},
            "checksums": checksums,
            "source_hashes": source_hashes,
            "verified_files": len(source_paths),
        }

    @staticmethod
    def _unsafe_path(message: str) -> ValueError:
        error = ValueError(message)
        error.code = "unsafe_legacy_path"  # type: ignore[attr-defined]
        return error

    def _validate_item_dir(self, item_dir: Path) -> None:
        if item_dir.is_symlink():
            raise self._unsafe_path(f"legacy item directory is a symlink: {item_dir}")
        try:
            item_root = item_dir.resolve(strict=True)
            legacy_root = self.legacy.items_dir.resolve(strict=True)
        except OSError as exc:
            raise self._unsafe_path(f"cannot resolve legacy item directory: {item_dir}") from exc
        if item_root.parent != legacy_root:
            raise self._unsafe_path(f"legacy item directory escapes items root: {item_dir}")

    def _validate_input_path(self, path: Path, item_dir: Path) -> None:
        if path.is_symlink():
            raise self._unsafe_path(f"legacy input is a symlink: {path}")
        try:
            resolved = path.resolve(strict=True)
            item_root = item_dir.resolve(strict=True)
        except OSError as exc:
            raise self._unsafe_path(f"cannot resolve legacy input: {path}") from exc
        if resolved != item_root and item_root not in resolved.parents:
            raise self._unsafe_path(f"legacy input escapes item directory: {path}")

    @staticmethod
    def _validate_expected_media(
        item_id: str,
        data: dict[str, Any],
        audio_files: list[Path],
        video_files: list[Path],
        image_files: list[Path],
    ) -> None:
        for kind, files in (("audio", audio_files), ("video", video_files)):
            if len(files) > 1:
                error = ValueError(f"multiple legacy {kind} files for {item_id}")
                error.code = "ambiguous_legacy_media"  # type: ignore[attr-defined]
                raise error
            if data.get(f"has_{kind}") and not files:
                error = ValueError(f"item.yaml expects {kind}, but no {kind} file exists")
                error.code = "missing_expected_media"  # type: ignore[attr-defined]
                raise error
        if data.get("has_images") and not image_files:
            error = ValueError("item.yaml expects images, but no image files exist")
            error.code = "missing_expected_media"  # type: ignore[attr-defined]
            raise error

    def _validate_destination(
        self, expected: list[Asset], existing: list[Asset],
    ) -> dict[str, str] | None:
        expected_by_path = {asset.path: asset for asset in expected}
        if len(expected_by_path) != len(expected):
            return {"code": "asset_record_conflict", "message": "duplicate legacy asset paths"}
        for asset in existing:
            expected_asset = expected_by_path.get(asset.path)
            if expected_asset is None or _asset_signature(asset) != _asset_signature(expected_asset):
                return {
                    "code": "asset_record_conflict",
                    "message": "existing SQLite asset records differ from legacy media",
                }
        for asset in expected:
            destination = self.brain.asset_store.path_for(asset)
            if destination.exists() and (
                not destination.is_file() or _sha256(destination) != asset.sha256
            ):
                return {
                    "code": "asset_destination_conflict",
                    "message": "asset destination exists with different bytes",
                    "path": str(destination),
                }
        return None

    async def _apply_item(
        self,
        item: Item,
        asset_sources: dict[str, Path],
        assets: list[Asset],
        existing_assets: list[Asset],
        source_hashes: dict[Path, str],
        *,
        insert_item: bool,
    ) -> int:
        final_dir = self.brain.config.assets_dir / item.id
        existing_paths = {asset.path for asset in existing_assets}
        missing_records = [asset for asset in assets if asset.path not in existing_paths]
        need_copy = [
            asset for asset in assets
            if not self.brain.asset_store.path_for(asset).exists()
        ]

        staged = await self.brain.asset_store.stage(
            item.id,
            audio_path=next((asset_sources[a.path] for a in assets if a.kind == "audio"), None),
            image_paths=[asset_sources[a.path] for a in assets if a.kind == "image"],
            video_path=next((asset_sources[a.path] for a in assets if a.kind == "video"), None),
            created_at=item.created_at,
        ) if need_copy else None
        transaction = None
        try:
            async with self.brain.index.transaction() as transaction:
                if insert_item:
                    await self.brain.index._insert(item)
                if missing_records:
                    await self.brain.index._insert_assets(missing_records)
                if staged is not None:
                    if final_dir.exists():
                        await self.brain.asset_store.promote_missing(
                            staged, {asset.path for asset in need_copy},
                        )
                    else:
                        await self.brain.asset_store.promote(staged)
                for asset in assets:
                    destination = self.brain.asset_store.path_for(asset)
                    if _sha256(destination) != asset.sha256:
                        raise RuntimeError(f"asset checksum verification failed: {destination}")
                    await self.brain.asset_store.make_read_only(asset)
                await self._verify_source_hashes(source_hashes)
        except BaseException:
            if staged is not None and (transaction is None or not transaction.committed):
                await self.brain.asset_store.discard(staged)
            raise
        return len(need_copy)

    async def _verify_source_hashes(self, expected: dict[Path, str]) -> None:
        for path, digest in expected.items():
            actual = await asyncio.to_thread(_sha256, path)
            if actual != digest:
                raise RuntimeError(f"legacy source changed while migrating: {path}")

    @staticmethod
    def _issue(
        report: dict[str, Any], item_id: str, code: str, message: str,
        path: str | None = None,
    ) -> None:
        issue = {"item_id": item_id, "code": code, "message": message}
        if path is not None:
            issue["path"] = path
        report["issues"].append(issue)
