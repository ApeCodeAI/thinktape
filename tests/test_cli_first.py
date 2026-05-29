"""Tests for the AI-friendly CLI workflow."""

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_cli(data_dir: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["BRAINDUMP_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "braindump", *args],
        cwd=ROOT,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_json(stdout: str) -> dict:
    return json.loads(stdout)


def test_init_creates_config_dirs_and_database(tmp_path: Path):
    result = run_cli(tmp_path, "init", "--data-dir", str(tmp_path), "--json")

    assert result.returncode == 0, result.stderr
    payload = parse_json(result.stdout)
    assert payload["ok"] is True
    assert payload["created_config"] is True
    assert Path(payload["config_path"]).exists()
    assert Path(payload["db_path"]).exists()
    assert (tmp_path / "media" / "text").is_dir()


def test_cli_add_list_show_search_and_stats_json(tmp_path: Path):
    init = run_cli(tmp_path, "init", "--data-dir", str(tmp_path), "--json")
    assert init.returncode == 0, init.stderr

    add = run_cli(
        tmp_path,
        "add",
        "今天想讲 AI friendly CLI first 的产品记录方式 #产品",
        "--tag",
        "writing",
        "--json",
    )
    assert add.returncode == 0, add.stderr
    added = parse_json(add.stdout)
    assert added["ok"] is True
    assert added["source"] == "cli"
    assert added["tags"] == ["产品", "writing"]

    note_id = str(added["id"])
    note_path = tmp_path / added["file_path"]
    assert note_path.exists()
    assert "source: cli" in note_path.read_text(encoding="utf-8")

    listed = run_cli(tmp_path, "list", "--json")
    assert listed.returncode == 0, listed.stderr
    listed_payload = parse_json(listed.stdout)
    assert listed_payload["notes"][0]["id"] == added["id"]
    assert listed_payload["notes"][0]["source"] == "cli"

    shown = run_cli(tmp_path, "show", note_id, "--json")
    assert shown.returncode == 0, shown.stderr
    shown_payload = parse_json(shown.stdout)
    assert "CLI first" in shown_payload["note"]["content"]
    assert shown_payload["note"]["tags"] == ["产品", "writing"]

    searched = run_cli(tmp_path, "search", "friendly", "--json")
    assert searched.returncode == 0, searched.stderr
    search_payload = parse_json(searched.stdout)
    assert [note["id"] for note in search_payload["notes"]] == [added["id"]]

    stats = run_cli(tmp_path, "stats", "--json")
    assert stats.returncode == 0, stats.stderr
    stats_payload = parse_json(stats.stdout)
    assert stats_payload["total"] == 1
    assert stats_payload["by_source"] == {"cli": 1}

    rebuilt = run_cli(tmp_path, "rebuild-index")
    assert rebuilt.returncode == 0, rebuilt.stderr

    rebuilt_stats = run_cli(tmp_path, "stats", "--json")
    assert rebuilt_stats.returncode == 0, rebuilt_stats.stderr
    rebuilt_payload = parse_json(rebuilt_stats.stdout)
    assert rebuilt_payload["total"] == 1
    assert rebuilt_payload["by_source"] == {"cli": 1}
