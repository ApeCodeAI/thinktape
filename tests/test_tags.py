"""Tests for inline #hashtag parsing and Item.all_tags union."""
from __future__ import annotations

from datetime import datetime

from thinktape.models import Item
from thinktape.tags import extract_hashtags


def _item(content: str, tags: list[str] | None = None) -> Item:
    now = datetime.now()
    return Item(id="x", created_at=now, updated_at=now, tags=tags or [], content=content)


def test_extract_basic_cjk_and_ascii():
    assert extract_hashtags("记录一下 #工作 和 #idea") == ["工作", "idea"]


def test_extract_nested_parent_child():
    assert extract_hashtags("#工作/会议 安排") == ["工作/会议"]


def test_extract_dedup_preserves_order():
    assert extract_hashtags("#a #b #a #c") == ["a", "b", "c"]


def test_extract_ignores_heading_and_csharp_and_url_fragment():
    # "# 标题" is a Markdown heading (space after #), not a tag.
    assert extract_hashtags("# 标题") == []
    # "C#" — the # is not preceded by whitespace.
    assert extract_hashtags("我用 C# 写的") == []
    # URL fragment — # not at a word boundary.
    assert extract_hashtags("see https://x.com/p#section now") == []


def test_extract_trailing_slash_stripped():
    assert extract_hashtags("#工作/ done") == ["工作"]


def test_extract_empty():
    assert extract_hashtags("") == []
    assert extract_hashtags("no tags here") == []


def test_all_tags_union_explicit_first_then_inline():
    it = _item("正文里有 #工作 和 #生活", tags=["手动"])
    assert it.all_tags == ["手动", "工作", "生活"]


def test_all_tags_dedupes_explicit_and_inline_overlap():
    it = _item("写了 #工作", tags=["工作", "手动"])
    assert it.all_tags == ["工作", "手动"]


def test_all_tags_explicit_only_when_no_hashtags():
    it = _item("plain body", tags=["手动"])
    assert it.all_tags == ["手动"]
