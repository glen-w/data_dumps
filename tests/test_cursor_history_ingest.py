"""Cursor History ingest smoke tests (synthetic fixture only)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from data_dumps.ingest import pick_source
from data_dumps.paths import raw_dir
from data_dumps.sources.cursor_history import (
    FORBIDDEN_COLUMN_NAMES,
    CursorHistorySource,
)

FORBIDDEN_COLUMNS = FORBIDDEN_COLUMN_NAMES


def make_mini_cursor_history_dir(path: Path) -> Path:
    root = path / "mini_cursor_history"
    root.mkdir(parents=True)
    (root / "EXPORT_MANIFEST.md").write_text(
        "# mini cursor history fixture\n", encoding="utf-8"
    )
    json_dir = root / "json"
    json_dir.mkdir()
    session = {
        "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "title": "Refactor ingest loader",
        "createdAt": "2026-03-01T10:00:00+00:00",
        "lastUpdatedAt": "2026-03-01T11:00:00+00:00",
        "messageCount": 3,
        "messages": [
            {
                "id": "m1",
                "role": "user",
                "content": (
                    "please fix the loader; api_key=sk-abcdefghijklmnopqrstuvwxyz012345"
                    " and email me at secret@example.com"
                ),
                "createdAt": "2026-03-01T10:00:00Z",
            },
            {
                "id": "m2",
                "role": "assistant",
                "content": "I'll inspect the source.",
                "createdAt": "2026-03-01T10:01:00Z",
                "toolCalls": {
                    "name": "read_file",
                    "toolCallId": "tc-1",
                    "status": "completed",
                    "rawArgs": '{"path": "sources/foo.py", "token": "ghp_abcdefghijklmnopqrstuvwxyz0123456789"}',
                    "result": "ok",
                },
            },
            {
                "id": "m3",
                "role": "assistant",
                "content": "done",
                "createdAt": "2026-03-01T10:05:00Z",
            },
        ],
        "toolCalls": [],
        "composerMeta": {
            "composerId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "name": "Refactor ingest loader",
            "unifiedMode": "agent",
            "isAgentic": True,
            "status": "completed",
        },
        "source": "test",
        "exportedAt": "2026-03-01T12:00:00+00:00",
        "exporter": "fixture",
    }
    (json_dir / "2026-03-01_Refactor_ingest_loader_aaaaaaaa.json").write_text(
        json.dumps(session), encoding="utf-8"
    )
    headers = {
        "count": 1,
        "sessions": [
            {
                "composerId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "workspaceId": "ws-test",
                "createdAt": 1740823200000,
                "lastUpdatedAt": 1740826800000,
                "isArchived": 0,
                "isSubagent": 0,
                "subagentTypeName": None,
                "parsed_name": "Refactor ingest loader",
            }
        ],
    }
    (root / "composer-headers-inventory.json").write_text(
        json.dumps(headers), encoding="utf-8"
    )

    transcript_dir = (
        root
        / "agent-transcripts"
        / "Users-test-project"
        / "ffffffff-1111-2222-3333-444444444444"
    )
    transcript_dir.mkdir(parents=True)
    lines = [
        json.dumps(
            {
                "role": "user",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "<timestamp>Sunday, Mar 2, 2026, 9:00 AM (UTC+1)"
                                "</timestamp>\n<user_query>\nhello\n</user_query>"
                            ),
                        }
                    ]
                },
            }
        ),
        json.dumps(
            {
                "role": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "hi"},
                        {
                            "type": "tool_use",
                            "id": "toolu-1",
                            "name": "Shell",
                            "input": {"command": "ls"},
                        },
                    ]
                },
            }
        ),
    ]
    (transcript_dir / "ffffffff-1111-2222-3333-444444444444.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return root


def _all_columns(conn: duckdb.DuckDBPyConnection) -> set[str]:
    rows = conn.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'cursor_history'
        """).fetchall()
    return {r[0].lower() for r in rows}


def test_detect_and_pick_source(tmp_path):
    root = make_mini_cursor_history_dir(tmp_path)
    assert CursorHistorySource().detect(root)
    assert pick_source(root) is not None
    assert pick_source(root).name == "cursor_history"
    assert not CursorHistorySource().detect(tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    assert pick_source(tmp_path / "empty") is None


def test_load_counts_and_forbidden_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data_root"))
    root = make_mini_cursor_history_dir(tmp_path)
    conn = duckdb.connect(str(tmp_path / "wh.duckdb"))
    CursorHistorySource().load(root, conn)

    n_sess = conn.execute("SELECT count(*) FROM cursor_history.sessions").fetchone()[0]
    n_msg = conn.execute("SELECT count(*) FROM cursor_history.messages").fetchone()[0]
    n_tools = conn.execute("SELECT count(*) FROM cursor_history.tool_calls").fetchone()[
        0
    ]
    assert n_sess == 2
    assert n_msg >= 4
    assert n_tools >= 2

    cols = _all_columns(conn)
    assert not (cols & {c.lower() for c in FORBIDDEN_COLUMNS})

    kinds = {
        r[0]
        for r in conn.execute(
            "SELECT source_kind FROM cursor_history.sessions"
        ).fetchall()
    }
    assert "composer" in kinds
    assert "agent_transcript" in kinds

    inv = CursorHistorySource().inventory(conn)
    assert "cursor_history:" in inv["summary"]
    assert inv["sessions"] == 2

    raw = raw_dir("cursor_history")
    assert (raw / "json").is_dir()
    assert (raw / "agent-transcripts").is_dir()
    assert (raw / "EXPORT_MANIFEST.md").is_file()
    assert not (raw / "markdown").exists()

    user_text = conn.execute("""
        SELECT text FROM cursor_history.messages
        WHERE role = 'user' AND session_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        """).fetchone()[0]
    assert "sk-" not in user_text
    assert "[REDACTED_OPENAI_KEY]" in user_text
    assert "secret@example.com" in user_text  # emails stay (Tools scans them)

    args = conn.execute("""
        SELECT args_json FROM cursor_history.tool_calls
        WHERE tool_call_id = 'tc-1'
        """).fetchone()[0]
    assert "ghp_" not in args
    assert "[REDACTED_GITHUB_PAT]" in args


def test_redact_secrets_unit():
    from data_dumps.sources.cursor_history import redact_secrets

    assert "[REDACTED_OPENAI_KEY]" in (
        redact_secrets("key sk-abcdefghijklmnopqrstuv") or ""
    )
    assert redact_secrets(None) is None


def test_cli_ingest(tmp_path, monkeypatch):
    from data_dumps.ingest import main

    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data_root"))
    root = make_mini_cursor_history_dir(tmp_path)
    db = tmp_path / "cli.duckdb"
    assert main([str(root), "--db", str(db)]) == 0
    conn = duckdb.connect(str(db), read_only=True)
    assert conn.execute("SELECT count(*) FROM cursor_history.sessions").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM cursor_history.models").fetchone()[0] >= 0


def test_rematerialize_skip_same_source(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data_root"))
    root = make_mini_cursor_history_dir(tmp_path)
    src = CursorHistorySource()
    conn = duckdb.connect(str(tmp_path / "wh1.duckdb"))
    src.load(root, conn)
    dest = raw_dir("cursor_history")
    marker = (dest / "source_path.txt").read_text(encoding="utf-8")
    json_mtime = (dest / "json" / next((dest / "json").glob("*.json")).name).stat().st_mtime_ns
    conn2 = duckdb.connect(str(tmp_path / "wh2.duckdb"))
    src.load(root, conn2)
    assert (dest / "source_path.txt").read_text(encoding="utf-8") == marker
    assert (
        dest / "json" / next((dest / "json").glob("*.json")).name
    ).stat().st_mtime_ns == json_mtime
    assert conn2.execute("SELECT count(*) FROM cursor_history.sessions").fetchone()[0] == 2


def test_composer_prefers_over_transcript_same_uuid(tmp_path, monkeypatch):
    """When UUID overlaps, composer message bodies win; transcript only merges metadata."""
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data_root"))
    root = make_mini_cursor_history_dir(tmp_path)
    # Overwrite transcript to share composer UUID and a distinct project slug.
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    tdir = root / "agent-transcripts" / "Users-overlap-project" / sid
    tdir.mkdir(parents=True)
    (tdir / f"{sid}.jsonl").write_text(
        '{"role":"user","message":{"content":[{"type":"text","text":"TRANSCRIPT_ONLY_BODY"}]}}\n',
        encoding="utf-8",
    )
    conn = duckdb.connect(str(tmp_path / "wh.duckdb"))
    CursorHistorySource().load(root, conn)
    bodies = [
        r[0]
        for r in conn.execute(
            "SELECT text FROM cursor_history.messages WHERE session_id = ?",
            [sid],
        ).fetchall()
    ]
    assert not any(b and "TRANSCRIPT_ONLY_BODY" in b for b in bodies)
    kind, project = conn.execute(
        """
        SELECT source_kind, project_slug FROM cursor_history.sessions
        WHERE session_id = ?
        """,
        [sid],
    ).fetchone()
    assert kind == "merged"
    assert project == "Users-overlap-project"
