"""Ollama app SQLite → DuckDB.

The macOS app stores chats in ``~/Library/Application Support/Ollama/db.sqlite``
(Linux: ``~/.ollama/db.sqlite``). There is no export zip. Message text is kept
(product is chat). Attachment bytes, the ``users`` row (email), ``settings``
(device id), and ``browser_state`` are not loaded.

``~/.ollama`` models and ``id_ed25519`` are never opened. A consistent copy is
taken with ``sqlite3.Connection.backup`` (WAL included; the app file is not
copied into ``raw/ollama/``). Sanitized JSONL under ``raw/ollama/`` is the
rebuild source. Warehouse text is redacted; the JSONL keeps the snapshot text.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir
from data_dumps.sources.cursor_history import redact_secrets

LOCAL_TZ = ZoneInfo("Europe/Paris")
SLUG = "ollama"

FORBIDDEN_COLUMN_NAMES = {
    "email",
    "email_address",
    "phone",
    "phone_number",
    "ip",
    "ip_address",
    "login_ip",
    "device_id",
    "data",
    "browser_state",
}

OLLAMA_TABLES = [
    "ollama.chats",
    "ollama.messages",
    "ollama.tool_calls",
    "ollama.attachments",
]

_TOOL_TEXT_MAX = 4_000
_JSONL = {
    "chats": "chats.jsonl",
    "messages": "messages.jsonl",
    "tool_calls": "tool_calls.jsonl",
    "attachments": "attachments.jsonl",
}

_CHAT_COLS = [
    "chat_id",
    "title",
    "created_at_utc",
    "created_at_local",
    "year",
    "month",
]
_MESSAGE_COLS = [
    "message_id",
    "chat_id",
    "ordinal",
    "role",
    "text",
    "thinking",
    "model_name",
    "model_family",
    "model_tag",
    "model_cloud",
    "model_ollama_host",
    "char_count",
    "thinking_chars",
    "thinking_seconds",
    "stream",
    "created_at_utc",
    "created_at_local",
    "updated_at_utc",
    "updated_at_local",
    "year",
    "month",
    "weekday",
    "hour",
]
_TOOL_COLS = [
    "tool_call_id",
    "message_id",
    "chat_id",
    "tool_name",
    "arguments_text",
    "result_text",
]
_ATTACH_COLS = [
    "attachment_id",
    "message_id",
    "chat_id",
    "filename",
    "extension",
    "byte_size",
]
_WHEN = {
    "created_at_utc",
    "created_at_local",
    "updated_at_utc",
    "updated_at_local",
}


def model_parts(slug: str | None) -> tuple[str | None, str | None]:
    """``gemma3:12b`` → ``("gemma", "12b")``."""
    if not slug or not str(slug).strip():
        return None, None
    name, sep, tag = str(slug).partition(":")
    match = re.match(r"[A-Za-z]+", name.strip())
    family = match.group(0).lower() if match else name.strip().lower() or None
    size = tag.strip() if sep and tag.strip() else None
    return family or None, size


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
    return bool(value)


def _truncate(text: str | None, limit: int = _TOOL_TEXT_MAX) -> str | None:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    stripped = value.strip()
    return stripped or None


def _parse_ts(value: Any) -> tuple[datetime | None, datetime | None]:
    """Return naive UTC and Europe/Paris datetimes."""
    if value is None or value == "":
        return None, None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None, None
    else:
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    ts_utc = parsed.astimezone(UTC).replace(tzinfo=None)
    ts_local = parsed.astimezone(LOCAL_TZ).replace(tzinfo=None)
    return ts_utc, ts_local


def _local_parts(
    ts_local: datetime | None,
) -> tuple[int | None, int | None, int | None, int | None]:
    if ts_local is None:
        return None, None, None, None
    return ts_local.year, ts_local.month, ts_local.isoweekday(), ts_local.hour


def _thinking_seconds(start: Any, end: Any) -> float | None:
    start_utc, _ = _parse_ts(start)
    end_utc, _ = _parse_ts(end)
    if start_utc is None or end_utc is None:
        return None
    delta = (end_utc - start_utc).total_seconds()
    if delta < 0:
        return None
    return delta


def _extension(filename: str | None) -> str | None:
    if not filename:
        return None
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix or None


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat(sep=" ")
        else:
            out[key] = value
    return out


def _from_jsonable(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in _WHEN:
        value = out.get(key)
        if isinstance(value, str) and value:
            out[key] = datetime.fromisoformat(value)
        elif value in ("", None):
            out[key] = None
    return out


def _sqlite_candidate(path: Path) -> Path | None:
    if path.is_file() and path.name == "db.sqlite":
        return path
    if path.is_dir():
        nested = path / "db.sqlite"
        if nested.is_file():
            return nested
    return None


def _schema_ok(db_path: Path) -> bool:
    if db_path.name == "state.vscdb":
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return False
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "chats" not in tables or "messages" not in tables:
            return False
        cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    return "thinking" in cols and "model_name" in cols


def _looks_like_raw(path: Path) -> bool:
    if not path.is_dir():
        return False
    manifest = path / "manifest.json"
    messages = path / _JSONL["messages"]
    if not manifest.is_file() or not messages.is_file():
        return False
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return False
    return isinstance(payload, dict) and payload.get("slug") == SLUG


def snapshot_db(db_path: Path) -> Path:
    """Consistent backup, including the WAL. Caller deletes the temp file.

    Opened read-only but not ``immutable``, so SQLite applies ``db.sqlite-wal``.
    """
    db_path = db_path.resolve()
    fd, tmp_name = tempfile.mkstemp(prefix="ollama_snap_", suffix=".sqlite")
    os.close(fd)
    tmp = Path(tmp_name)
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return tmp


def _unlink_sqlite(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def _read_snapshot(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return _read_connection(conn)
    finally:
        conn.close()


def _read_connection(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    chats: list[dict[str, Any]] = []
    for row in conn.execute("SELECT id, title, created_at FROM chats"):
        ts_utc, ts_local = _parse_ts(row["created_at"])
        year, month, _, _ = _local_parts(ts_local)
        chats.append(
            {
                "chat_id": str(row["id"]),
                "title": row["title"] or "",
                "created_at_utc": ts_utc,
                "created_at_local": ts_local,
                "year": year,
                "month": month,
            }
        )

    messages: list[dict[str, Any]] = []
    ordinals: dict[str, int] = {}
    for row in conn.execute("""
        SELECT id, chat_id, role, content, thinking, stream, model_name,
               model_cloud, model_ollama_host, created_at, updated_at,
               thinking_time_start, thinking_time_end
        FROM messages
        ORDER BY chat_id, id
        """):
        chat_id = str(row["chat_id"])
        ordinal = ordinals.get(chat_id, 0)
        ordinals[chat_id] = ordinal + 1
        created_utc, created_local = _parse_ts(row["created_at"])
        updated_utc, updated_local = _parse_ts(row["updated_at"])
        year, month, weekday, hour = _local_parts(created_local)
        messages.append(
            {
                "message_id": int(row["id"]),
                "chat_id": chat_id,
                "ordinal": ordinal,
                "role": row["role"] or "unknown",
                "text": _text(row["content"]),
                "thinking": _text(row["thinking"]),
                "model_name": _text(row["model_name"]),
                "model_cloud": _as_bool(row["model_cloud"]),
                "model_ollama_host": _as_bool(row["model_ollama_host"]),
                "stream": bool(_as_bool(row["stream"])),
                "created_at_utc": created_utc,
                "created_at_local": created_local,
                "updated_at_utc": updated_utc,
                "updated_at_local": updated_local,
                "thinking_seconds": _thinking_seconds(
                    row["thinking_time_start"], row["thinking_time_end"]
                ),
                "year": year,
                "month": month,
                "weekday": weekday,
                "hour": hour,
            }
        )

    chat_of = {m["message_id"]: m["chat_id"] for m in messages}
    tools: list[dict[str, Any]] = []
    tool_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tool_calls'"
    ).fetchone()
    if tool_table is not None:
        for row in conn.execute("""
            SELECT id, message_id, function_name, function_arguments, function_result
            FROM tool_calls
            ORDER BY id
            """):
            message_id = int(row["message_id"])
            tools.append(
                {
                    "tool_call_id": int(row["id"]),
                    "message_id": message_id,
                    "chat_id": chat_of.get(message_id),
                    "tool_name": row["function_name"] or "",
                    "arguments_text": _text(row["function_arguments"]),
                    "result_text": _text(row["function_result"]),
                }
            )

    attachments: list[dict[str, Any]] = []
    attach_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'attachments'"
    ).fetchone()
    if attach_table is not None:
        for row in conn.execute("""
            SELECT id, message_id, filename, length(data) AS byte_size
            FROM attachments
            ORDER BY id
            """):
            message_id = int(row["message_id"])
            filename = row["filename"] or ""
            attachments.append(
                {
                    "attachment_id": int(row["id"]),
                    "message_id": message_id,
                    "chat_id": chat_of.get(message_id),
                    "filename": filename,
                    "extension": _extension(filename),
                    "byte_size": int(row["byte_size"] or 0),
                }
            )
    return {
        "chats": chats,
        "messages": messages,
        "tool_calls": tools,
        "attachments": attachments,
    }


def _write_jsonl(dest: Path, bundle: dict[str, list[dict[str, Any]]]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for key, filename in _JSONL.items():
        path = dest / filename
        with path.open("w", encoding="utf-8") as handle:
            for row in bundle[key]:
                payload = json.dumps(_jsonable(row), ensure_ascii=False)
                handle.write(payload + "\n")
    manifest = {
        "slug": SLUG,
        "chats": len(bundle["chats"]),
        "messages": len(bundle["messages"]),
        "tool_calls": len(bundle["tool_calls"]),
        "attachments": len(bundle["attachments"]),
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def _read_jsonl(path: Path) -> dict[str, list[dict[str, Any]]]:
    def load(name: str) -> list[dict[str, Any]]:
        file_path = path / _JSONL[name]
        if not file_path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in file_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(_from_jsonable(json.loads(line)))
        return rows

    return {key: load(key) for key in _JSONL}


def _warehouse_bundle(
    bundle: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    messages: list[dict[str, Any]] = []
    for row in bundle["messages"]:
        text = redact_secrets(row.get("text"))
        thinking = redact_secrets(row.get("thinking"))
        family, tag = model_parts(row.get("model_name"))
        messages.append(
            {
                **row,
                "text": text,
                "thinking": thinking,
                "model_family": family,
                "model_tag": tag,
                "char_count": len(text) if text else 0,
                "thinking_chars": len(thinking) if thinking else 0,
            }
        )
    tools: list[dict[str, Any]] = []
    for row in bundle["tool_calls"]:
        tools.append(
            {
                **row,
                "arguments_text": _truncate(redact_secrets(row.get("arguments_text"))),
                "result_text": _truncate(redact_secrets(row.get("result_text"))),
            }
        )
    return {
        "chats": list(bundle["chats"]),
        "messages": messages,
        "tool_calls": tools,
        "attachments": list(bundle["attachments"]),
    }


def _frame(rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


class OllamaSource:
    name = SLUG

    def detect(self, path: Path) -> bool:
        try:
            path = path.resolve()
        except OSError:
            return False
        candidate = _sqlite_candidate(path)
        if candidate is not None and _schema_ok(candidate):
            return True
        return _looks_like_raw(path)

    def tables(self) -> list[str]:
        return list(OLLAMA_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        path = path.resolve()
        candidate = _sqlite_candidate(path)
        if candidate is not None and _schema_ok(candidate):
            snap = snapshot_db(candidate)
            try:
                bundle = _read_snapshot(snap)
            finally:
                _unlink_sqlite(snap)
            _write_jsonl(raw_dir(self.name), bundle)
        elif _looks_like_raw(path):
            bundle = _read_jsonl(path)
            owned = raw_dir(self.name).resolve()
            if path.resolve() != owned:
                _write_jsonl(owned, bundle)
        else:
            raise ValueError(f"not an Ollama app database: {path}")

        ready = _warehouse_bundle(bundle)
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SLUG}")
        for table in ("attachments", "tool_calls", "messages", "chats"):
            conn.execute(f"DROP TABLE IF EXISTS {SLUG}.{table}")

        frames = {
            "chats": _frame(ready["chats"], _CHAT_COLS),
            "messages": _frame(ready["messages"], _MESSAGE_COLS),
            "tool_calls": _frame(ready["tool_calls"], _TOOL_COLS),
            "attachments": _frame(ready["attachments"], _ATTACH_COLS),
        }
        for table, frame in frames.items():
            view = f"_ol_{table}"
            conn.register(view, frame)
            conn.execute(f"CREATE TABLE {SLUG}.{table} AS SELECT * FROM {view}")
            conn.unregister(view)

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict:
        row = conn.execute(f"""
            SELECT
                (SELECT count(*)::BIGINT FROM {SLUG}.chats),
                (SELECT count(*)::BIGINT FROM {SLUG}.messages),
                (SELECT count(*)::BIGINT FROM {SLUG}.tool_calls),
                (SELECT count(*)::BIGINT FROM {SLUG}.attachments),
                (SELECT min(created_at_local)::DATE FROM {SLUG}.messages),
                (SELECT max(created_at_local)::DATE FROM {SLUG}.messages)
            """).fetchone()
        assert row is not None
        n_chats, n_msg, n_tools, n_attach, first_day, last_day = row
        span = f", {first_day} → {last_day}" if first_day and last_day else ""
        return {
            "chats": int(n_chats or 0),
            "messages": int(n_msg or 0),
            "tool_calls": int(n_tools or 0),
            "attachments": int(n_attach or 0),
            "first_day": first_day,
            "last_day": last_day,
            "summary": (
                f"ollama: {n_chats} chats, {n_msg} messages, "
                f"{n_tools} tool calls, {n_attach} attachments{span}"
            ),
        }
