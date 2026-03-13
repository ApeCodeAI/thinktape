"""YAML frontmatter read/write utilities for .md note files.

Frontmatter format:
---
title: Short title
tags: [tag1, tag2]
mood: 思考
created: 2026-03-12T22:35:13+08:00
source: telegram
type: text
summary: Core content summary...
---

Actual note content...
"""

import json
import logging
from pathlib import Path

import yaml

logger = logging.getLogger("braindump.frontmatter")

_FM_DELIMITER = "---"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text.

    Returns (metadata_dict, body_content). If no frontmatter found,
    returns ({}, original_text).
    """
    if not text.startswith(_FM_DELIMITER):
        return {}, text

    # Find the closing delimiter
    end = text.find(f"\n{_FM_DELIMITER}", len(_FM_DELIMITER))
    if end == -1:
        return {}, text

    yaml_block = text[len(_FM_DELIMITER) : end].strip()
    # Body starts after the closing --- and optional blank line separator
    body_start = end + 1 + len(_FM_DELIMITER)
    body = text[body_start:]
    # Strip up to two leading newlines (the \n after --- and blank separator line)
    if body.startswith("\n\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]

    try:
        meta = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError as e:
        logger.warning("Failed to parse frontmatter YAML: %s", e)
        return {}, text

    if not isinstance(meta, dict):
        return {}, text

    return meta, body


def render_frontmatter(meta: dict, body: str) -> str:
    """Render a complete .md file with YAML frontmatter + body content."""
    if not meta:
        return body

    yaml_str = yaml.dump(
        meta,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).rstrip("\n")

    return f"{_FM_DELIMITER}\n{yaml_str}\n{_FM_DELIMITER}\n\n{body}"


def merge_frontmatter(existing: dict, updates: dict) -> dict:
    """Merge new fields into existing frontmatter.

    Special handling for 'tags': merge lists without duplicates.
    Other fields: updates overwrite existing.
    """
    merged = dict(existing)

    for key, val in updates.items():
        if key == "tags" and key in merged:
            # Merge tag lists, preserving order, no duplicates
            old_tags = merged["tags"] if isinstance(merged["tags"], list) else []
            new_tags = val if isinstance(val, list) else []
            seen = set()
            combined = []
            for t in old_tags + new_tags:
                if t not in seen:
                    seen.add(t)
                    combined.append(t)
            merged["tags"] = combined
        else:
            merged[key] = val

    return merged


def build_creation_frontmatter(
    created_at: str,
    source: str,
    media_type: str,
    tags: list[str],
) -> dict:
    """Build the basic frontmatter dict written at note creation time."""
    meta: dict = {}
    meta["created"] = created_at
    meta["source"] = source
    meta["type"] = media_type
    if tags:
        meta["tags"] = tags
    return meta


def build_summary_frontmatter(
    ai_title: str,
    ai_tags_json: str,
    ai_mood: str,
    ai_summary: str,
) -> dict:
    """Build frontmatter fields from AI summary results."""
    meta: dict = {}
    meta["title"] = ai_title
    if ai_tags_json:
        try:
            ai_tags = json.loads(ai_tags_json)
            if isinstance(ai_tags, list):
                meta["tags"] = ai_tags
        except (json.JSONDecodeError, TypeError):
            pass
    meta["mood"] = ai_mood
    meta["summary"] = ai_summary
    return meta


def write_frontmatter_to_file(filepath: Path, updates: dict) -> None:
    """Read an existing .md file, merge frontmatter updates, and rewrite.

    If the file already has frontmatter, merge. Otherwise, prepend new frontmatter.
    """
    if not filepath.exists():
        logger.warning("File not found, cannot write frontmatter: %s", filepath)
        return

    text = filepath.read_text(encoding="utf-8")
    existing_meta, body = parse_frontmatter(text)
    merged = merge_frontmatter(existing_meta, updates)
    new_text = render_frontmatter(merged, body)
    filepath.write_text(new_text, encoding="utf-8")


def read_frontmatter_from_file(filepath: Path) -> tuple[dict, str]:
    """Read and parse frontmatter from a .md file.

    Returns (metadata_dict, body_content).
    """
    if not filepath.exists():
        return {}, ""
    text = filepath.read_text(encoding="utf-8")
    return parse_frontmatter(text)
