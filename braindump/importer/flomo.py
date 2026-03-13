"""Flomo HTML export importer.

Parses the exported HTML file from Flomo, extracts notes with:
- Text content (preserving paragraphs)
- Tags (e.g. #tag, #parent/child)
- Created time
- Attached images (copied to media/image/)
"""

import hashlib
import logging
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from braindump.config import get_config, get_timezone
from braindump.database import get_db, init_db

logger = logging.getLogger("braindump.importer")

# Match hashtags in text: #tag or #parent/child, but not URLs or CSS colors
TAG_PATTERN = re.compile(r"(?:^|\s)#([a-zA-Z\u4e00-\u9fff][\w/\u4e00-\u9fff]*)")


def _extract_tags(text: str) -> list[str]:
    """Extract hashtags from text content."""
    return list(dict.fromkeys(TAG_PATTERN.findall(text)))  # unique, preserve order


def _strip_tags_from_text(text: str) -> str:
    """Remove standalone hashtag lines from text, keep inline tags."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Remove lines that are only tags (possibly with spaces)
        if stripped and all(
            part.startswith("#") or part == ""
            for part in stripped.split()
        ):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _compute_display_date(created_at: datetime, day_boundary_hour: int) -> str:
    """Compute display_date: before boundary hour counts as previous day."""
    if created_at.hour < day_boundary_hour:
        d = created_at.date() - timedelta(days=1)
    else:
        d = created_at.date()
    return d.isoformat()


def _make_flomo_filename(created_at: datetime, index: int, ext: str) -> str:
    """Generate filename: YYYYMMDD_HHmmss_fl{index}.{ext}"""
    ts = created_at.strftime("%Y%m%d_%H%M%S")
    return f"{ts}_fl{index}.{ext}"


def parse_flomo_html(html_path: Path) -> list[dict]:
    """Parse Flomo export HTML and return list of note dicts."""
    with open(html_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    notes = []
    memos = soup.find_all("div", class_="memo")

    for idx, memo in enumerate(memos):
        # Extract time
        time_div = memo.find("div", class_="time")
        if not time_div:
            continue
        time_str = time_div.get_text(strip=True)
        try:
            created_at = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=get_timezone())
        except ValueError:
            logger.warning("Cannot parse time '%s', skipping memo #%d", time_str, idx)
            continue

        # Extract content
        content_div = memo.find("div", class_="content")
        if not content_div:
            continue

        # Get text content, preserving paragraph breaks
        paragraphs = content_div.find_all("p")
        if paragraphs:
            text_parts = []
            for p in paragraphs:
                text_parts.append(p.get_text())
            content_text = "\n".join(text_parts)
        else:
            content_text = content_div.get_text()

        content_text = content_text.strip()

        # Extract tags from content
        tags = _extract_tags(content_text)

        # Clean content (remove tag-only lines)
        clean_content = _strip_tags_from_text(content_text)

        # Extract images
        files_div = memo.find("div", class_="files")
        images = []
        if files_div:
            for img in files_div.find_all("img"):
                src = img.get("src", "")
                if src:
                    images.append(src)

        notes.append({
            "content": clean_content,
            "tags": tags,
            "created_at": created_at,
            "images": images,
            "source_index": idx,
        })

    return notes


async def import_flomo(export_path: str):
    """Import Flomo export into braindump database.

    Args:
        export_path: Path to the Flomo export directory (containing the HTML file and file/ dir)
    """
    cfg = get_config()
    export_dir = Path(export_path)

    # Find the HTML file
    html_files = list(export_dir.glob("*.html"))
    if not html_files:
        logger.error("No HTML file found in %s", export_dir)
        return
    html_path = html_files[0]
    logger.info("Parsing: %s", html_path.name)

    # Parse
    notes = parse_flomo_html(html_path)
    logger.info("Found %d notes", len(notes))

    if not notes:
        return

    # Initialize database
    await init_db()
    db = await get_db()

    now = datetime.now(get_timezone()).isoformat()
    imported = 0
    skipped = 0
    images_copied = 0

    try:
        for note in notes:
            created_at = note["created_at"]
            display_date = _compute_display_date(created_at, cfg.general.day_boundary_hour)
            tags_str = ",".join(note["tags"])

            # Check for duplicate (same source + time + content hash)
            content_hash = hashlib.md5((note["content"] or "").encode()).hexdigest()[:8]
            source_id = f"fl_{created_at.strftime('%Y%m%d_%H%M%S')}_{content_hash}"

            cursor = await db.execute(
                "SELECT id FROM notes WHERE source = 'flomo' AND source_id = ?",
                (source_id,),
            )
            if await cursor.fetchone():
                skipped += 1
                continue

            # Determine media_type
            has_images = len(note["images"]) > 0
            media_type = "image" if has_images and not note["content"] else "text"

            # Write .md file for text content
            text_file_path = None
            if note["content"]:
                year, month, day = display_date.split("-")
                ts = created_at.strftime("%Y%m%d_%H%M%S")
                md_fname = f"{ts}_fl{content_hash}.md"
                md_dir = cfg.media_dir / "text" / year / month / day
                md_dir.mkdir(parents=True, exist_ok=True)
                md_dest = md_dir / md_fname
                md_dest.write_text(note["content"], encoding="utf-8")
                text_file_path = f"media/text/{year}/{month}/{day}/{md_fname}"

            # Insert note
            file_path_value = text_file_path  # will be overridden if has images
            cursor = await db.execute(
                """INSERT INTO notes
                   (content, media_type, file_path, created_at, display_date, imported_at,
                    source, source_id, tags, transcribe_status)
                   VALUES (?, ?, ?, ?, ?, ?, 'flomo', ?, ?, 'not_needed')""",
                (
                    note["content"],
                    media_type,
                    file_path_value,
                    created_at.isoformat(),
                    display_date,
                    now,
                    source_id,
                    tags_str,
                ),
            )
            note_id = cursor.lastrowid

            # Copy images
            for img_idx, img_src in enumerate(note["images"]):
                # Sanitize img_src: reject absolute paths and .. segments
                if img_src.startswith("/") or ".." in img_src.split("/"):
                    logger.warning("Rejecting unsafe image path: %s", img_src)
                    continue
                src_path = (export_dir / img_src).resolve()
                if not src_path.is_relative_to(export_dir.resolve()):
                    logger.warning("Image path escapes export dir: %s", img_src)
                    continue
                if not src_path.exists():
                    logger.warning("Image not found: %s", src_path)
                    continue

                ext = src_path.suffix.lstrip(".")
                display_d = _compute_display_date(created_at, cfg.general.day_boundary_hour)
                year, month, day = display_d.split("-")
                fname = _make_flomo_filename(created_at, note["source_index"] * 10 + img_idx, ext)

                dest_dir = cfg.media_dir / "image" / year / month / day
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / fname
                rel_path = f"media/image/{year}/{month}/{day}/{fname}"

                shutil.copy2(src_path, dest_path)

                # Insert attachment
                file_size = dest_path.stat().st_size
                await db.execute(
                    """INSERT INTO attachments
                       (note_id, file_path, media_type, file_size, sort_order)
                       VALUES (?, ?, 'image', ?, ?)""",
                    (note_id, rel_path, file_size, img_idx),
                )

                # Set first image as note's file_path
                if img_idx == 0:
                    await db.execute(
                        "UPDATE notes SET file_path = ?, file_size = ? WHERE id = ?",
                        (rel_path, file_size, note_id),
                    )

                images_copied += 1

            imported += 1

        await db.commit()
        logger.info("Import complete: imported=%d, skipped=%d, images=%d", imported, skipped, images_copied)

    finally:
        await db.close()
