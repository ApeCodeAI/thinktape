"""Tests for wikilink parsing and bi-directional link index."""
from __future__ import annotations

import pytest

from thinktape.core import ThinkTape
from thinktape.links import WIKILINK_RE, extract_links, find_concept_matches


# ---------- parser ----------

def test_extract_concept_and_item_links():
    text = "我在想 [[Agent 记忆]]，参考 [[20260619-143052-a3f8]] 那条。"
    links = extract_links(text)
    assert len(links) == 2
    assert {"type": "concept", "target": "Agent 记忆"} in links
    assert {"type": "item", "target": "20260619-143052-a3f8"} in links


def test_extract_dedups_repeated_links():
    text = "[[A]] then [[A]] and [[B]] and [[A]]"
    links = extract_links(text)
    assert links == [
        {"type": "concept", "target": "A"},
        {"type": "concept", "target": "B"},
    ]


def test_extract_ignores_empty_and_no_links():
    assert extract_links("") == []
    assert extract_links("no wikilinks here") == []
    assert extract_links("[[]] empty") == []


def test_extract_strips_whitespace():
    links = extract_links("[[  Agent 记忆  ]]")
    assert links == [{"type": "concept", "target": "Agent 记忆"}]


def test_wikilink_regex_matches_chinese():
    matches = WIKILINK_RE.findall("我想 [[认知科学]] 这个话题")
    assert matches == ["认知科学"]


def test_find_concept_matches_case_insensitive():
    class _Fake:
        def __init__(self, content: str):
            self.content = content

    items = [_Fake("Agent 记忆很重要"), _Fake("无关内容"), _Fake("agent 记忆 again")]
    found = find_concept_matches("Agent 记忆", items)
    assert len(found) == 2


# ---------- index ----------

async def test_links_indexed_on_add(brain: ThinkTape):
    item = await brain.add("讨论 [[Agent 记忆]] 这个概念")
    outgoing = await brain.index.get_outgoing_links(item.id)
    assert outgoing == [{"type": "concept", "target": "Agent 记忆"}]


async def test_links_updated_on_content_change(brain: ThinkTape):
    a = await brain.add("初始内容 [[Topic A]]")
    out1 = await brain.index.get_outgoing_links(a.id)
    assert any(link["target"] == "Topic A" for link in out1)
    await brain.update(a.id, content="改成 [[Topic B]] 现在")
    out2 = await brain.index.get_outgoing_links(a.id)
    targets = {link["target"] for link in out2}
    assert "Topic A" not in targets
    assert "Topic B" in targets


async def test_item_id_links_create_backlinks(brain: ThinkTape):
    target = await brain.add("the target item")
    source = await brain.add(f"reference to [[{target.id}]]")
    backlinks = await brain.get_backlinks(target.id)
    assert any(b["id"] == source.id and b["via"] == "item" for b in backlinks)


async def test_concept_references_query(brain: ThinkTape):
    a = await brain.add("explore [[Agent 记忆]]")
    b = await brain.add("more thoughts on [[Agent 记忆]]")
    await brain.add("unrelated")
    refs = await brain.index.get_concept_references("Agent 记忆")
    assert set(refs) == {a.id, b.id}


async def test_all_concepts_with_counts(brain: ThinkTape):
    await brain.add("[[Alpha]]")
    await brain.add("[[Alpha]] again")
    await brain.add("[[Beta]]")
    concepts = await brain.all_concepts()
    names = {c["name"]: c["count"] for c in concepts}
    assert names == {"Alpha": 2, "Beta": 1}


async def test_get_concept_items_text_match_and_wikilink(brain: ThinkTape):
    # Item A explicitly uses [[Topic]]
    a = await brain.add("about [[Topic]]")
    # Item B mentions Topic in plain text
    b = await brain.add("I think Topic is interesting")
    # Item C is unrelated
    await brain.add("nothing here")
    items = await brain.get_concept_items("Topic")
    ids = {it.id for it in items}
    assert a.id in ids
    assert b.id in ids


async def test_rebuild_index_rebuilds_links(brain: ThinkTape):
    a = await brain.add("[[X]] and [[Y]]")
    await brain.index.db.execute("DELETE FROM links")
    await brain.index.db.commit()
    assert await brain.index.get_outgoing_links(a.id) == []
    n = await brain.rebuild_index()
    assert n >= 1
    out = await brain.index.get_outgoing_links(a.id)
    targets = {link["target"] for link in out}
    assert targets == {"X", "Y"}


async def test_delete_clears_outgoing_links(brain: ThinkTape):
    a = await brain.add("[[X]]")
    await brain.index.delete(a.id)
    out = await brain.index.get_outgoing_links(a.id)
    assert out == []


async def test_get_links_resolves_item_targets(brain: ThinkTape):
    target = await brain.add("target body")
    src = await brain.add(f"see [[{target.id}]]")
    out = await brain.get_links(src.id)
    item_links = [link for link in out if link["type"] == "item"]
    assert len(item_links) == 1
    assert item_links[0]["target"] == target.id
    assert item_links[0]["item"]["id"] == target.id


async def test_get_links_resolves_concept_matches(brain: ThinkTape):
    src = await brain.add("references [[Topic]]")
    await brain.add("Topic is mentioned in this other item too")
    out = await brain.get_links(src.id)
    concept_links = [link for link in out if link["type"] == "concept"]
    assert concept_links
    assert concept_links[0]["target"] == "Topic"
    assert concept_links[0]["match_count"] >= 1
