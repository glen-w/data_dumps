"""Ollama ingest smoke tests (synthetic fixture only)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import duckdb

from data_dumps.ingest import pick_source
from data_dumps.paths import raw_dir
from data_dumps.sources.ollama import FORBIDDEN_COLUMN_NAMES, OllamaSource

BLOB_SENTINEL = b"BLOB_SENTINEL_DO_NOT_STORE"
EMAIL = "hidden@example.com"
DEVICE_ID = "device-SHOULD-NOT-LOAD"
BROWSER_STATE = "COOKIE_SHOULD_NOT_LOAD"


def make_mini_ollama_db(path: Path) -> Path:
    root = path / "Ollama"
    root.mkdir(parents=True)
    db_path = root / "db.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY,
            device_id TEXT NOT NULL DEFAULT '',
            working_dir TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE users (
            name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            plan TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE chats (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            browser_state TEXT
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            thinking TEXT NOT NULL DEFAULT '',
            stream BOOLEAN NOT NULL DEFAULT 0,
            model_name TEXT,
            model_cloud BOOLEAN,
            model_ollama_host BOOLEAN,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            thinking_time_start TIMESTAMP,
            thinking_time_end TIMESTAMP,
            tool_result TEXT
        );
        CREATE TABLE tool_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            function_name TEXT NOT NULL,
            function_arguments TEXT NOT NULL,
            function_result TEXT
        );
        CREATE TABLE attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            data BLOB NOT NULL
        );
        """)
    conn.execute(
        "INSERT INTO settings (id, device_id, working_dir) VALUES (1, ?, ?)",
        (DEVICE_ID, "/Users/secret/home"),
    )
    conn.execute(
        "INSERT INTO users (name, email, plan) VALUES (?, ?, ?)",
        ("Ada", EMAIL, "pro"),
    )
    conn.execute(
        "INSERT INTO chats (id, title, created_at, browser_state) VALUES (?, ?, ?, ?)",
        ("c1", "Hello models", "2025-08-06 15:50:58+02:00", BROWSER_STATE),
    )
    conn.execute(
        "INSERT INTO chats (id, title, created_at) VALUES (?, ?, ?)",
        ("c2", "Later notes", "2026-03-02 09:00:00+01:00"),
    )
    conn.execute(
        """
        INSERT INTO messages (
            chat_id, role, content, thinking, model_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "c1",
            "user",
            "fix the loader; api_key=sk-abcdefghijklmnopqrstuvwxyz012345",
            "",
            None,
            "2025-08-06 15:50:58+02:00",
            "2025-08-06 15:50:58+02:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO messages (
            chat_id, role, content, thinking, model_name, model_cloud,
            created_at, updated_at, thinking_time_start, thinking_time_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "c1",
            "assistant",
            "I will look at the source.",
            "Checking the schema first.",
            "gemma3:12b",
            0,
            "2025-08-06 15:51:30+02:00",
            "2025-08-06 15:51:30+02:00",
            "2025-08-06 15:51:00+02:00",
            "2025-08-06 15:51:20+02:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO messages (chat_id, role, content, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "c2",
            "user",
            "ping",
            "2026-03-02 09:00:00+01:00",
            "2026-03-02 09:00:00+01:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO messages (
            chat_id, role, content, model_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "c2",
            "assistant",
            "pong",
            "qwen3:8b",
            "2026-03-02 09:00:05+01:00",
            "2026-03-02 09:00:05+01:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO tool_calls (
            message_id, type, function_name, function_arguments, function_result
        ) VALUES (2, 'function', 'read_file', ?, 'ok')
        """,
        (
            '{"path": "sources/foo.py", "token": "ghp_abcdefghijklmnopqrstuvwxyz0123456789"}',
        ),
    )
    conn.execute(
        "INSERT INTO attachments (message_id, filename, data) VALUES (1, ?, ?)",
        ("notes.py", BLOB_SENTINEL),
    )
    conn.commit()
    conn.close()
    return root


def _columns(conn: duckdb.DuckDBPyConnection) -> set[str]:
    rows = conn.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ollama'
        """).fetchall()
    return {row[0].lower() for row in rows}


def _text_blobs(conn: duckdb.DuckDBPyConnection) -> str:
    parts: list[str] = []
    for sql in (
        "SELECT coalesce(title, '') FROM ollama.chats",
        "SELECT coalesce(text, '') FROM ollama.messages",
        "SELECT coalesce(thinking, '') FROM ollama.messages",
        "SELECT coalesce(arguments_text, '') FROM ollama.tool_calls",
        "SELECT coalesce(result_text, '') FROM ollama.tool_calls",
        "SELECT coalesce(filename, '') FROM ollama.attachments",
    ):
        parts.extend(row[0] for row in conn.execute(sql).fetchall())
    return "\n".join(parts)


def test_detect_and_pick_source(tmp_path: Path):
    root = make_mini_ollama_db(tmp_path)
    assert OllamaSource().detect(root)
    assert OllamaSource().detect(root / "db.sqlite")
    picked = pick_source(root)
    assert picked is not None
    assert picked.name == "ollama"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not OllamaSource().detect(empty)
    assert pick_source(empty) is None
    other = tmp_path / "other.sqlite"
    sqlite3.connect(other).execute("CREATE TABLE notes (id INT)").close()
    assert not OllamaSource().detect(other)
    bare = tmp_path / "dot-ollama"
    (bare / "models").mkdir(parents=True)
    (bare / "id_ed25519").write_text("not-a-key", encoding="utf-8")
    assert not OllamaSource().detect(bare)
    vscdb = tmp_path / "state.vscdb"
    vscdb.write_bytes(b"not sqlite")
    assert not OllamaSource().detect(vscdb)


def test_load_counts_and_forbidden_columns(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data_root"))
    root = make_mini_ollama_db(tmp_path)
    conn = duckdb.connect(str(tmp_path / "wh.duckdb"))
    OllamaSource().load(root, conn)

    assert conn.execute("SELECT count(*) FROM ollama.chats").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM ollama.messages").fetchone()[0] == 4
    assert conn.execute("SELECT count(*) FROM ollama.tool_calls").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM ollama.attachments").fetchone()[0] == 1

    cols = _columns(conn)
    assert not (cols & {name.lower() for name in FORBIDDEN_COLUMN_NAMES})

    stored = _text_blobs(conn)
    assert BLOB_SENTINEL.decode() not in stored
    assert EMAIL not in stored
    assert DEVICE_ID not in stored
    assert BROWSER_STATE not in stored
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in stored
    assert "[REDACTED_OPENAI_KEY]" in stored
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in stored

    family = conn.execute("""
        SELECT model_family, model_tag
        FROM ollama.messages
        WHERE model_name = 'gemma3:12b'
        """).fetchone()
    assert family == ("gemma", "12b")

    hour = conn.execute("""
        SELECT hour FROM ollama.messages
        WHERE chat_id = 'c1' AND role = 'user'
        """).fetchone()
    assert hour is not None
    assert hour[0] == 15

    inv = OllamaSource().inventory(conn)
    assert inv["summary"].startswith("ollama: 2 chats, 4 messages")
    assert inv["attachments"] == 1

    raw = raw_dir("ollama")
    assert (raw / "manifest.json").is_file()
    assert (raw / "messages.jsonl").is_file()
    assert (raw / "attachments.jsonl").is_file()
    assert not (raw / "db.sqlite").exists()
    assert BLOB_SENTINEL.decode() not in (raw / "attachments.jsonl").read_text()
    assert EMAIL not in (raw / "messages.jsonl").read_text()
    # Snapshot text stays in JSONL; the warehouse copy is redacted.
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" in (raw / "messages.jsonl").read_text()


def test_reload_from_raw_jsonl(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data_root"
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(data_root))
    root = make_mini_ollama_db(tmp_path)
    conn = duckdb.connect(str(tmp_path / "wh.duckdb"))
    OllamaSource().load(root, conn)
    conn.close()

    raw = raw_dir("ollama")
    conn = duckdb.connect(str(tmp_path / "wh2.duckdb"))
    OllamaSource().load(raw, conn)
    assert conn.execute("SELECT count(*) FROM ollama.messages").fetchone()[0] == 4
    text = conn.execute(
        "SELECT text FROM ollama.messages WHERE role = 'user' AND chat_id = 'c1'"
    ).fetchone()
    assert text is not None
    assert "sk-" not in (text[0] or "")


def test_snapshot_includes_uncheckpointed_wal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data_root"))
    root = make_mini_ollama_db(tmp_path)
    writer = sqlite3.connect(root / "db.sqlite")
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("""
        INSERT INTO messages (chat_id, role, content, created_at, updated_at)
        VALUES ('c2', 'user', 'from wal', '2026-03-02 10:00:00+01:00',
                '2026-03-02 10:00:00+01:00')
        """)
    writer.commit()
    assert (root / "db.sqlite-wal").stat().st_size > 0
    conn = duckdb.connect(str(tmp_path / "wal.duckdb"))
    try:
        OllamaSource().load(root, conn)
        found = conn.execute(
            "SELECT count(*) FROM ollama.messages WHERE text = 'from wal'"
        ).fetchone()
        assert found is not None
        assert found[0] == 1
    finally:
        writer.close()


def test_cli_ingest(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data_root"))
    root = make_mini_ollama_db(tmp_path)
    db_path = tmp_path / "cli.duckdb"
    from data_dumps.ingest import main

    assert main([str(root), "--db", str(db_path)]) == 0
    conn = duckdb.connect(str(db_path))
    assert conn.execute("SELECT count(*) FROM ollama.messages").fetchone()[0] == 4
