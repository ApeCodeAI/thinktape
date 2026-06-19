"""Tests for the braindump CLI."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from braindump import cli as cli_module
from braindump.cli import cli


@pytest.fixture
def runner(tmp_path, monkeypatch):
    """CLI runner with isolated data dir."""
    data_dir = tmp_path / "braindump-data"
    data_dir.mkdir()
    monkeypatch.setenv("BRAINDUMP_DATA_DIR", str(data_dir))
    return CliRunner(), data_dir


def _invoke(runner_pair, *args, input: str | None = None):
    runner, _ = runner_pair
    result = runner.invoke(cli, list(args), input=input, catch_exceptions=False)
    return result


def test_version(runner):
    r = _invoke(runner, "version")
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["version"] == "2.0.0"


def test_add_and_list(runner):
    r = _invoke(runner, "add", "hello from cli")
    assert r.exit_code == 0, r.output
    item = json.loads(r.output)
    assert item["content"] == "hello from cli"
    assert item["source"] == "cli"
    assert item["type"] == "thought"
    assert item["status"] == "active"

    r = _invoke(runner, "list")
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["total"] == 1
    assert data["items"][0]["content"] == "hello from cli"


def test_add_with_tags_and_type(runner):
    r = _invoke(runner, "add", "interesting article",
                "--type", "bookmark",
                "--bookmark-url", "https://example.com",
                "--tag", "AI", "--tag", "Agent")
    assert r.exit_code == 0
    item = json.loads(r.output)
    assert item["type"] == "bookmark"
    assert item["bookmark_url"] == "https://example.com"
    assert set(item["tags"]) == {"AI", "Agent"}


def test_add_tags_csv(runner):
    r = _invoke(runner, "add", "note",
                "--tags", "a, b, #c")
    assert r.exit_code == 0
    item = json.loads(r.output)
    assert set(item["tags"]) == {"a", "b", "c"}


def test_add_from_stdin(runner):
    r = _invoke(runner, "add", "-", input="from stdin\n")
    assert r.exit_code == 0
    item = json.loads(r.output)
    assert item["content"] == "from stdin"


def test_add_from_file(runner, tmp_path):
    src = tmp_path / "note.md"
    src.write_text("# heading\nbody\n", encoding="utf-8")
    r = _invoke(runner, "add", "--file", str(src))
    assert r.exit_code == 0
    item = json.loads(r.output)
    assert "heading" in item["content"]


def test_add_empty_fails(runner):
    r = _invoke(runner, "add", "")
    assert r.exit_code == 1
    err = json.loads(r.stderr if hasattr(r, "stderr") else r.output)
    assert err["code"] == "EMPTY_CONTENT"


def test_get(runner):
    r = _invoke(runner, "add", "to get")
    item_id = json.loads(r.output)["id"]

    r = _invoke(runner, "get", item_id)
    assert r.exit_code == 0
    item = json.loads(r.output)
    assert item["id"] == item_id
    assert item["content"] == "to get"


def test_get_content_only(runner):
    r = _invoke(runner, "add", "raw markdown here")
    item_id = json.loads(r.output)["id"]
    r = _invoke(runner, "get", item_id, "--content")
    assert r.exit_code == 0
    assert r.output.strip() == "raw markdown here"


def test_get_not_found(runner):
    r = _invoke(runner, "get", "20990101-000000-0000")
    assert r.exit_code == 1


def test_get_human(runner):
    _invoke(runner, "add", "human readable test", "--tag", "x")
    r = _invoke(runner, "list")
    item_id = json.loads(r.output)["items"][0]["id"]
    r = _invoke(runner, "get", item_id, "--human")
    assert r.exit_code == 0
    assert "human readable test" in r.output
    assert "#x" in r.output


def test_list_human(runner):
    _invoke(runner, "add", "first thought")
    _invoke(runner, "add", "second thought")
    r = _invoke(runner, "list", "--human")
    assert r.exit_code == 0
    assert "first thought" in r.output
    assert "second thought" in r.output


def test_list_filter_by_type(runner):
    _invoke(runner, "add", "thought one")
    _invoke(runner, "add", "bookmark one", "--type", "bookmark",
            "--bookmark-url", "https://e.com")
    r = _invoke(runner, "list", "--type", "bookmark")
    data = json.loads(r.output)
    assert data["total"] == 1
    assert data["items"][0]["type"] == "bookmark"


def test_update_content_and_tags(runner):
    r = _invoke(runner, "add", "original")
    item_id = json.loads(r.output)["id"]

    r = _invoke(runner, "update", item_id,
                "--content", "updated",
                "--tag", "alpha", "--tag", "beta")
    assert r.exit_code == 0
    item = json.loads(r.output)
    assert item["content"] == "updated"
    assert set(item["tags"]) == {"alpha", "beta"}


def test_update_no_changes(runner):
    r = _invoke(runner, "add", "x")
    item_id = json.loads(r.output)["id"]
    r = _invoke(runner, "update", item_id)
    assert r.exit_code == 1


def test_delete_soft(runner):
    r = _invoke(runner, "add", "doomed")
    item_id = json.loads(r.output)["id"]

    r = _invoke(runner, "delete", item_id)
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["deleted"] == item_id
    assert data["hard"] is False

    r = _invoke(runner, "list")
    assert json.loads(r.output)["total"] == 0

    r = _invoke(runner, "list", "--status", "deleted")
    assert json.loads(r.output)["total"] == 1


def test_delete_hard(runner, tmp_path):
    r = _invoke(runner, "add", "doomed hard")
    item_id = json.loads(r.output)["id"]

    r = _invoke(runner, "delete", item_id, "--force")
    assert r.exit_code == 0

    r = _invoke(runner, "get", item_id)
    assert r.exit_code == 1


def test_search(runner):
    _invoke(runner, "add", "apple pie recipe")
    _invoke(runner, "add", "banana bread")
    r = _invoke(runner, "search", "apple")
    data = json.loads(r.output)
    assert data["total"] == 1
    assert "apple" in data["items"][0]["content"]


def test_stats(runner):
    _invoke(runner, "add", "one")
    _invoke(runner, "add", "two", "--type", "bookmark", "--bookmark-url", "https://x")
    r = _invoke(runner, "stats")
    data = json.loads(r.output)
    assert data["total"] == 2
    assert data["by_type"]["thought"] == 1
    assert data["by_type"]["bookmark"] == 1


def test_tags_command(runner):
    _invoke(runner, "add", "a", "--tag", "foo")
    _invoke(runner, "add", "b", "--tag", "bar")
    r = _invoke(runner, "tags")
    data = json.loads(r.output)
    assert set(data["tags"]) == {"foo", "bar"}


def test_config(runner):
    r = _invoke(runner, "config")
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert "data_dir" in data
    assert "llm" in data
    assert "web" in data


def test_summarize_disabled(runner):
    r = _invoke(runner, "summarize", "20990101-000000-0000")
    assert r.exit_code == 1


def test_rebuild_index(runner):
    _invoke(runner, "add", "to rebuild")
    r = _invoke(runner, "rebuild-index")
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["rebuilt"] == 1
