"""Tests for IndexDB."""
from __future__ import annotations

from pathlib import Path

import pytest

from thinktape.core import ThinkTape


async def test_add_and_list(brain: ThinkTape):
    a = await brain.add("first thought", type="thought")
    b = await brain.add("second thought", type="thought", tags=["focus"])
    c = await brain.add("https://example.com a link", type="bookmark", bookmark_url="https://example.com")

    items = await brain.list(limit=10)
    assert len(items) == 3
    # newest first
    assert items[0].id == c.id

    bookmarks = await brain.list(type="bookmark")
    assert len(bookmarks) == 1
    assert bookmarks[0].id == c.id

    focused = await brain.list(tag="focus")
    assert len(focused) == 1 and focused[0].id == b.id


async def test_search_fts(brain: ThinkTape):
    await brain.add("quick brown fox")
    await brain.add("lazy dog")
    await brain.add("foxtrot dance")

    results = await brain.search("fox")
    contents = sorted(r.content for r in results)
    assert "quick brown fox" in contents
    assert "foxtrot dance" in contents
    assert "lazy dog" not in contents


async def test_search_chinese(brain: ThinkTape):
    await brain.add("今天写了一个 thinktape 工具")
    await brain.add("不相关的内容")
    results = await brain.search("thinktape")
    assert len(results) == 1


async def test_stats(brain: ThinkTape):
    await brain.add("a", type="thought")
    await brain.add("b", type="thought", tags=["t1"])
    await brain.add("c", type="bookmark", bookmark_url="https://x", tags=["t1", "t2"])
    stats = await brain.stats()
    assert stats.total == 3
    assert stats.by_type["thought"] == 2
    assert stats.by_type["bookmark"] == 1
    assert stats.by_tag["t1"] == 2
    assert stats.by_tag["t2"] == 1


async def test_inline_hashtags_filterable(brain: ThinkTape):
    a = await brain.add("记录一下 #工作 的想法")  # no explicit tags
    await brain.add("无关内容")
    focused = await brain.list(tag="工作")
    assert len(focused) == 1 and focused[0].id == a.id
    # union surfaces on the listed item
    assert "工作" in focused[0].tags


async def test_inline_and_explicit_union_in_stats_and_all_tags(brain: ThinkTape):
    await brain.add("正文 #工作 #生活", tags=["手动"])
    stats = await brain.stats()
    assert stats.by_tag["工作"] == 1
    assert stats.by_tag["生活"] == 1
    assert stats.by_tag["手动"] == 1
    assert set(await brain.all_tags()) >= {"工作", "生活", "手动"}


async def test_yaml_keeps_explicit_tags_only(brain: ThinkTape):
    item = await brain.add("派生 #工作 不写回 yaml", tags=["手动"])
    # The on-disk source of truth keeps only explicit tags...
    on_disk = await brain.store.get(item.id)
    assert on_disk.tags == ["手动"]
    # ...while the index/list view exposes the union.
    listed = await brain.list(tag="工作")
    assert len(listed) == 1


async def test_editing_content_updates_derived_tags(brain: ThinkTape):
    item = await brain.add("first #alpha")
    assert len(await brain.list(tag="alpha")) == 1
    await brain.update(item.id, content="now #beta only")
    assert await brain.list(tag="alpha") == []
    assert len(await brain.list(tag="beta")) == 1


async def test_soft_delete_excluded(brain: ThinkTape):
    a = await brain.add("keep me")
    b = await brain.add("delete me")
    await brain.delete(b.id)
    items = await brain.list()
    assert len(items) == 1 and items[0].id == a.id


async def test_rebuild_index(brain: ThinkTape):
    a = await brain.add("alpha")
    b = await brain.add("beta")
    # Clear the index by hand then rebuild from files.
    await brain.index.db.execute("DELETE FROM items")
    await brain.index.db.execute("DELETE FROM items_fts")
    await brain.index.db.commit()
    assert (await brain.list()) == []
    n = await brain.rebuild_index()
    assert n == 2
    items = await brain.list()
    assert {i.id for i in items} == {a.id, b.id}
