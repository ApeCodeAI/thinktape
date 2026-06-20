"""Wikilink parsing — [[concept]] and [[item-id]] extraction."""
from __future__ import annotations

import re
from typing import Any

WIKILINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
ITEM_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


def is_item_id(s: str) -> bool:
    return bool(ITEM_ID_RE.match(s))


def extract_links(content: str) -> list[dict[str, str]]:
    """Extract all [[wikilinks]] from content.

    Returns a list of {"type": "concept" | "item", "target": str},
    de-duplicated while preserving first-seen order.
    """
    if not content:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for match in WIKILINK_RE.finditer(content):
        target = match.group(1).strip()
        if not target:
            continue
        link_type = "item" if is_item_id(target) else "concept"
        key = (link_type, target)
        if key in seen:
            continue
        seen.add(key)
        out.append({"type": link_type, "target": target})
    return out


def find_concept_matches(concept: str, items: list[Any]) -> list[Any]:
    """Find items whose content contains the concept text (case-insensitive)."""
    needle = (concept or "").strip().lower()
    if not needle:
        return []
    matches: list[Any] = []
    for it in items:
        content = getattr(it, "content", "") or ""
        if needle in content.lower():
            matches.append(it)
    return matches


def make_snippet(content: str, needle: str, *, radius: int = 40) -> str:
    """Return a short snippet around the first occurrence of needle (case-insensitive)."""
    content = (content or "").replace("\n", " ").strip()
    if not needle:
        return content[: 2 * radius]
    lc = content.lower()
    pos = lc.find(needle.lower())
    if pos == -1:
        return content[: 2 * radius]
    start = max(0, pos - radius)
    end = min(len(content), pos + len(needle) + radius)
    out = content[start:end]
    if start > 0:
        out = "…" + out
    if end < len(content):
        out = out + "…"
    return out
