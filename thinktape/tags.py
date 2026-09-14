"""Inline hashtag parsing — #tag extraction from content.

Mirrors links.py: hashtags are derived from canonical SQLite content and are
indexed separately from explicit tags. Supports CJK, ASCII word chars, and
nested #parent/child.
"""
from __future__ import annotations

import re

# A # that starts the string or follows whitespace, then a tag whose first
# char is alphanumeric/underscore/CJK and may continue with '/' for nesting.
# Requiring whitespace/start before # avoids matching URL fragments (x#frag),
# C#, and Markdown headings ("# Heading" has a space, so it never matches).
HASHTAG_RE = re.compile(
    r"(?:^|(?<=\s))#([0-9A-Za-z_一-鿿][0-9A-Za-z_一-鿿/]*)"
)


def extract_hashtags(content: str) -> list[str]:
    """Extract bare #hashtag names from content (no leading '#').

    De-duplicated while preserving first-seen order for derived indexes and
    API display; explicit Item.tags remain separately stored in SQLite.
    """
    if not content:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in HASHTAG_RE.finditer(content):
        tag = match.group(1).strip().rstrip("/")
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out
