"""Tests for the YAML frontmatter utility module."""

import json
import tempfile
from pathlib import Path

from braindump.frontmatter import (
    parse_frontmatter,
    render_frontmatter,
    merge_frontmatter,
    build_creation_frontmatter,
    build_summary_frontmatter,
    write_frontmatter_to_file,
    read_frontmatter_from_file,
)


def test_parse_frontmatter_basic():
    text = "---\ntitle: Hello\ntags: [a, b]\n---\n\nBody content"
    meta, body = parse_frontmatter(text)
    assert meta["title"] == "Hello"
    assert meta["tags"] == ["a", "b"]
    assert body == "Body content"


def test_parse_frontmatter_no_frontmatter():
    text = "Just plain text without frontmatter."
    meta, body = parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_parse_frontmatter_empty_yaml():
    text = "---\n---\n\nBody"
    meta, body = parse_frontmatter(text)
    assert meta == {}
    assert body == "Body"


def test_parse_frontmatter_invalid_yaml():
    text = "---\n: bad: yaml: [unclosed\n---\n\nBody"
    meta, body = parse_frontmatter(text)
    # Should fall back gracefully
    assert isinstance(meta, dict)


def test_render_frontmatter():
    meta = {"title": "Test", "tags": ["a", "b"]}
    body = "Hello world"
    result = render_frontmatter(meta, body)
    assert result.startswith("---\n")
    assert "title: Test" in result
    assert result.endswith("\n\nHello world")


def test_render_frontmatter_empty_meta():
    body = "Just body"
    result = render_frontmatter({}, body)
    assert result == body


def test_roundtrip():
    meta = {"title": "Test Title", "tags": ["tag1", "tag2"], "mood": "思考"}
    body = "Original body content.\n\nWith paragraphs."
    rendered = render_frontmatter(meta, body)
    parsed_meta, parsed_body = parse_frontmatter(rendered)
    assert parsed_meta["title"] == meta["title"]
    assert parsed_meta["tags"] == meta["tags"]
    assert parsed_meta["mood"] == meta["mood"]
    assert parsed_body == body


def test_merge_frontmatter_tags():
    existing = {"title": "Old", "tags": ["a", "b"]}
    updates = {"title": "New", "tags": ["b", "c"]}
    merged = merge_frontmatter(existing, updates)
    assert merged["title"] == "New"
    assert merged["tags"] == ["a", "b", "c"]


def test_merge_frontmatter_new_fields():
    existing = {"created": "2026-01-01"}
    updates = {"title": "Hello", "mood": "日常"}
    merged = merge_frontmatter(existing, updates)
    assert merged["created"] == "2026-01-01"
    assert merged["title"] == "Hello"
    assert merged["mood"] == "日常"


def test_build_creation_frontmatter():
    fm = build_creation_frontmatter(
        created_at="2026-03-12T22:35:13+08:00",
        source="telegram",
        media_type="text",
        tags=["work", "idea"],
    )
    assert fm["created"] == "2026-03-12T22:35:13+08:00"
    assert fm["source"] == "telegram"
    assert fm["type"] == "text"
    assert fm["tags"] == ["work", "idea"]


def test_build_creation_frontmatter_no_tags():
    fm = build_creation_frontmatter(
        created_at="2026-03-12T22:35:13+08:00",
        source="web",
        media_type="text",
        tags=[],
    )
    assert "tags" not in fm


def test_build_summary_frontmatter():
    fm = build_summary_frontmatter(
        ai_title="关于 Agent 的思考",
        ai_tags_json=json.dumps(["agent", "LLM"]),
        ai_mood="思考",
        ai_summary="讨论了 Agent 系统的瓶颈...",
    )
    assert fm["title"] == "关于 Agent 的思考"
    assert fm["tags"] == ["agent", "LLM"]
    assert fm["mood"] == "思考"
    assert fm["summary"] == "讨论了 Agent 系统的瓶颈..."


def test_build_summary_frontmatter_bad_json():
    fm = build_summary_frontmatter(
        ai_title="Test",
        ai_tags_json="not valid json",
        ai_mood="日常",
        ai_summary="Summary",
    )
    assert fm["title"] == "Test"
    assert "tags" not in fm  # Bad JSON should be skipped


def test_write_and_read_frontmatter_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("Original content here.")
        tmp_path = Path(f.name)

    try:
        # Write frontmatter to a plain file
        write_frontmatter_to_file(tmp_path, {"title": "Hello", "tags": ["a"]})

        meta, body = read_frontmatter_from_file(tmp_path)
        assert meta["title"] == "Hello"
        assert meta["tags"] == ["a"]
        assert body == "Original content here."

        # Update with additional fields (merge)
        write_frontmatter_to_file(tmp_path, {"mood": "思考", "tags": ["a", "b"]})
        meta, body = read_frontmatter_from_file(tmp_path)
        assert meta["title"] == "Hello"
        assert meta["mood"] == "思考"
        assert meta["tags"] == ["a", "b"]
        assert body == "Original content here."
    finally:
        tmp_path.unlink()


def test_write_frontmatter_nonexistent_file():
    # Should not raise, just log warning
    write_frontmatter_to_file(Path("/nonexistent/file.md"), {"title": "test"})


def test_chinese_content_roundtrip():
    meta = {"title": "关于 Agent 落地的思考", "mood": "思考"}
    body = "讨论了当前 Agent 系统在实际业务中落地的三个关键瓶颈"
    rendered = render_frontmatter(meta, body)
    parsed_meta, parsed_body = parse_frontmatter(rendered)
    assert parsed_meta["title"] == "关于 Agent 落地的思考"
    assert parsed_body == body
