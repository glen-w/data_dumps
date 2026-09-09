"""Telegram Desktop JSON export → DuckDB.

Media files stay on disk; only result.json is copied under raw/telegram/.
Message IDs are per-chat; the grain is (chat_id, message_id).
Session IPs are dropped (same privacy rule as Spotify).
"""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

RESULT_JSON = "result.json"
LOCAL_TZ = ZoneInfo("Europe/Rome")


def parse_duration_sec(value: str | None) -> int | None:
    """Parse export durations like '0:11' or '1:02:03' to seconds."""
    if not value or not isinstance(value, str):
        return None
    parts = value.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def media_kind_of(msg: dict[str, Any]) -> str:
    if msg.get("photo"):
        return "photo"
    mt = msg.get("media_type")
    if isinstance(mt, str) and mt:
        return mt
    if msg.get("file"):
        return "file"
    if msg.get("contact_information"):
        return "contact"
    if msg.get("location_information"):
        return "location"
    if msg.get("poll"):
        return "poll"
    if msg.get("webpage"):
        return "webpage"
    return "none"


def flatten_text(value: Any) -> str | None:
    """Telegram ``text`` is a string or a list of strings / entity dicts."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for part in value:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                txt = part.get("text")
                if isinstance(txt, str):
                    parts.append(txt)
        return "".join(parts)
    return str(value)


def media_relpath_of(msg: dict[str, Any]) -> str | None:
    for key in ("photo", "file"):
        val = msg.get(key)
        if isinstance(val, str) and "/" in val and not val.startswith("("):
            return val
    return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ts_pair(msg: dict[str, Any]) -> tuple[datetime, datetime]:
    """Return naive UTC and Europe/Rome local timestamps."""
    unix = msg.get("date_unixtime")
    if unix is not None and str(unix).isdigit():
        ts_utc = datetime.fromtimestamp(int(unix), tz=UTC)
    else:
        raw = msg.get("date")
        if not isinstance(raw, str) or not raw:
            raise ValueError(f"message {msg.get('id')} has no date")
        ts_utc = datetime.fromisoformat(raw).replace(tzinfo=UTC)
    ts_local = ts_utc.astimezone(LOCAL_TZ)
    return ts_utc.replace(tzinfo=None), ts_local.replace(tzinfo=None)


def _payload_has_chats(payload: object) -> bool:
    return isinstance(payload, dict) and "chats" in payload


def _read_result_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not _payload_has_chats(payload):
        return None
    return payload


class TelegramSource:
    name = "telegram"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    names = [
                        n for n in zf.namelist() if n.rstrip("/").endswith(RESULT_JSON)
                    ]
                    if not names:
                        return False
                    payload = json.loads(zf.read(names[0]))
            except (
                OSError,
                zipfile.BadZipFile,
                json.JSONDecodeError,
                UnicodeDecodeError,
            ):
                return False
            return _payload_has_chats(payload)
        export = self._export_dir(path)
        if export is None:
            return False
        return _read_result_json(export / RESULT_JSON) is not None

    def _export_dir(self, path: Path) -> Path | None:
        if not path.is_dir():
            return None
        if (path / RESULT_JSON).is_file():
            return path
        nested = [
            p for p in path.iterdir() if p.is_dir() and (p / RESULT_JSON).is_file()
        ]
        if len(nested) == 1:
            return nested[0]
        return None

    def tables(self) -> list[str]:
        return [
            "telegram.account",
            "telegram.contacts",
            "telegram.sessions",
            "telegram.chats",
            "telegram.messages",
            "telegram.reactions",
        ]

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        result_path, export_root = self._materialize(path)
        with result_path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict) or "chats" not in payload:
            raise ValueError(f"{result_path} is not a Telegram Desktop result.json")

        account_df = self._account_frame(payload, export_root)
        contacts_df = self._contacts_frame(payload)
        sessions_df = self._sessions_frame(payload)
        chats_df, messages_df, reactions_df = self._chat_frames(payload)

        conn.execute("CREATE SCHEMA IF NOT EXISTS telegram")
        for table in (
            "reactions",
            "messages",
            "chats",
            "contacts",
            "sessions",
            "account",
        ):
            conn.execute(f"DROP TABLE IF EXISTS telegram.{table}")

        conn.execute("""
            CREATE TABLE telegram.account (
                user_id BIGINT,
                first_name VARCHAR,
                last_name VARCHAR,
                username VARCHAR,
                phone_number VARCHAR,
                bio VARCHAR,
                export_root VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE telegram.contacts (
                first_name VARCHAR,
                last_name VARCHAR,
                phone_number VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE telegram.sessions (
                app_name VARCHAR,
                app_version VARCHAR,
                device VARCHAR,
                platform VARCHAR,
                created TIMESTAMP,
                last_active TIMESTAMP,
                country VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE telegram.chats (
                chat_id BIGINT,
                name VARCHAR,
                type VARCHAR,
                n_messages BIGINT,
                n_service BIGINT,
                first_ts TIMESTAMP,
                last_ts TIMESTAMP
            )
            """)
        conn.execute("""
            CREATE TABLE telegram.messages (
                chat_id BIGINT,
                message_id BIGINT,
                event_type VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                from_name VARCHAR,
                from_id BIGINT,
                text VARCHAR,
                reply_to_message_id BIGINT,
                forwarded_from VARCHAR,
                edited BOOLEAN,
                action VARCHAR,
                media_kind VARCHAR,
                file_name VARCHAR,
                media_relpath VARCHAR,
                duration_sec INTEGER,
                width INTEGER,
                height INTEGER,
                webpage_url VARCHAR,
                webpage_title VARCHAR,
                year BIGINT,
                month BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE telegram.reactions (
                chat_id BIGINT,
                message_id BIGINT,
                emoji VARCHAR,
                count BIGINT
            )
            """)

        conn.register("_tg_account", account_df)
        conn.execute("INSERT INTO telegram.account BY NAME SELECT * FROM _tg_account")
        conn.unregister("_tg_account")

        conn.register("_tg_contacts", contacts_df)
        conn.execute("INSERT INTO telegram.contacts BY NAME SELECT * FROM _tg_contacts")
        conn.unregister("_tg_contacts")

        conn.register("_tg_sessions", sessions_df)
        conn.execute("INSERT INTO telegram.sessions BY NAME SELECT * FROM _tg_sessions")
        conn.unregister("_tg_sessions")

        conn.register("_tg_chats", chats_df)
        conn.execute("INSERT INTO telegram.chats BY NAME SELECT * FROM _tg_chats")
        conn.unregister("_tg_chats")

        conn.register("_tg_messages", messages_df)
        conn.execute("INSERT INTO telegram.messages BY NAME SELECT * FROM _tg_messages")
        conn.unregister("_tg_messages")

        conn.register("_tg_reactions", reactions_df)
        conn.execute(
            "INSERT INTO telegram.reactions BY NAME SELECT * FROM _tg_reactions"
        )
        conn.unregister("_tg_reactions")

    def _materialize(self, path: Path) -> tuple[Path, Path]:
        dest = raw_dir("telegram")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)

        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                json_name = next(
                    n for n in zf.namelist() if n.rstrip("/").endswith(RESULT_JSON)
                )
                zf.extract(json_name, dest)
            extracted = dest / json_name
            result_path = dest / RESULT_JSON
            if extracted != result_path:
                result_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(extracted), str(result_path))
                nested = extracted.parent
                if nested != dest and nested.exists():
                    shutil.rmtree(nested, ignore_errors=True)
            export_root = path
        else:
            src = self._export_dir(path)
            if src is None:
                raise FileNotFoundError(f"No {RESULT_JSON} in {path}")
            shutil.copy2(src / RESULT_JSON, dest / RESULT_JSON)
            export_root = src
            result_path = dest / RESULT_JSON

        (dest / "export_root.txt").write_text(str(export_root) + "\n", encoding="utf-8")
        return result_path, export_root

    def _account_frame(
        self, payload: dict[str, Any], export_root: Path
    ) -> pd.DataFrame:
        info = payload.get("personal_information") or {}
        return pd.DataFrame(
            [
                {
                    "user_id": _as_int(info.get("user_id")),
                    "first_name": info.get("first_name"),
                    "last_name": info.get("last_name"),
                    "username": info.get("username"),
                    "phone_number": info.get("phone_number"),
                    "bio": info.get("bio"),
                    "export_root": str(export_root),
                }
            ]
        )

    def _contacts_frame(self, payload: dict[str, Any]) -> pd.DataFrame:
        rows = []
        for item in (payload.get("contacts") or {}).get("list") or []:
            rows.append(
                {
                    "first_name": item.get("first_name"),
                    "last_name": item.get("last_name"),
                    "phone_number": item.get("phone_number"),
                }
            )
        if not rows:
            return pd.DataFrame(columns=["first_name", "last_name", "phone_number"])
        return pd.DataFrame(rows)

    def _sessions_frame(self, payload: dict[str, Any]) -> pd.DataFrame:
        rows = []
        for item in (payload.get("sessions") or {}).get("list") or []:
            created = item.get("created")
            last_active = item.get("last_active")
            rows.append(
                {
                    "app_name": item.get("application_name"),
                    "app_version": item.get("application_version"),
                    "device": item.get("device_model"),
                    "platform": item.get("platform"),
                    "created": datetime.fromisoformat(created) if created else None,
                    "last_active": (
                        datetime.fromisoformat(last_active) if last_active else None
                    ),
                    "country": item.get("last_country"),
                }
            )
        if not rows:
            return pd.DataFrame(
                columns=[
                    "app_name",
                    "app_version",
                    "device",
                    "platform",
                    "created",
                    "last_active",
                    "country",
                ]
            )
        return pd.DataFrame(rows)

    def _chat_frames(
        self, payload: dict[str, Any]
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        chat_rows: list[dict[str, Any]] = []
        message_rows: list[dict[str, Any]] = []
        reaction_rows: list[dict[str, Any]] = []

        chats = (payload.get("chats") or {}).get("list") or []
        for chat in chats:
            chat_id = _as_int(chat.get("id"))
            messages = chat.get("messages") or []
            n_service = sum(1 for m in messages if m.get("type") == "service")
            timestamps = [_ts_pair(m)[0] for m in messages] if messages else []
            chat_rows.append(
                {
                    "chat_id": chat_id,
                    "name": chat.get("name"),
                    "type": chat.get("type"),
                    "n_messages": sum(
                        1 for m in messages if m.get("type") != "service"
                    ),
                    "n_service": n_service,
                    "first_ts": min(timestamps) if timestamps else None,
                    "last_ts": max(timestamps) if timestamps else None,
                }
            )
            for msg in messages:
                message_id = _as_int(msg.get("id"))
                webpage = msg.get("webpage") or {}
                ts_utc, ts_local = _ts_pair(msg)
                message_rows.append(
                    {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "event_type": msg.get("type") or "message",
                        "ts_utc": ts_utc,
                        "ts_local": ts_local,
                        "from_name": msg.get("from"),
                        "from_id": _as_int(msg.get("from_id")),
                        "text": flatten_text(msg.get("text")),
                        "reply_to_message_id": _as_int(msg.get("reply_to_message_id")),
                        "forwarded_from": msg.get("forwarded_from"),
                        "edited": bool(msg.get("edited")),
                        "action": msg.get("action"),
                        "media_kind": media_kind_of(msg),
                        "file_name": msg.get("file_name"),
                        "media_relpath": media_relpath_of(msg),
                        "duration_sec": parse_duration_sec(msg.get("duration")),
                        "width": _as_int(msg.get("width")),
                        "height": _as_int(msg.get("height")),
                        "webpage_url": (
                            webpage.get("url") if isinstance(webpage, dict) else None
                        ),
                        "webpage_title": (
                            webpage.get("title") if isinstance(webpage, dict) else None
                        ),
                        "year": ts_local.year,
                        "month": ts_local.month,
                    }
                )
                for reaction in msg.get("reactions") or []:
                    reaction_rows.append(
                        {
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "emoji": reaction.get("emoji"),
                            "count": _as_int(reaction.get("count")) or 0,
                        }
                    )

        chats_df = (
            pd.DataFrame(chat_rows)
            if chat_rows
            else pd.DataFrame(
                columns=[
                    "chat_id",
                    "name",
                    "type",
                    "n_messages",
                    "n_service",
                    "first_ts",
                    "last_ts",
                ]
            )
        )
        messages_df = (
            pd.DataFrame(message_rows)
            if message_rows
            else pd.DataFrame(
                columns=[
                    "chat_id",
                    "message_id",
                    "event_type",
                    "ts_utc",
                    "ts_local",
                    "from_name",
                    "from_id",
                    "text",
                    "reply_to_message_id",
                    "forwarded_from",
                    "edited",
                    "action",
                    "media_kind",
                    "file_name",
                    "media_relpath",
                    "duration_sec",
                    "width",
                    "height",
                    "webpage_url",
                    "webpage_title",
                    "year",
                    "month",
                ]
            )
        )
        reactions_df = (
            pd.DataFrame(reaction_rows)
            if reaction_rows
            else pd.DataFrame(columns=["chat_id", "message_id", "emoji", "count"])
        )
        return chats_df, messages_df, reactions_df

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict:
        row = conn.execute("""
            SELECT
                count(*)::BIGINT AS n_events,
                count(*) FILTER (WHERE event_type = 'message')::BIGINT AS n_messages,
                count(DISTINCT chat_id)::BIGINT AS n_chats,
                min(ts_utc)::DATE AS first_day,
                max(ts_utc)::DATE AS last_day,
                count(*) FILTER (WHERE media_kind = 'photo')::BIGINT AS n_photos,
                count(*) FILTER (WHERE reply_to_message_id IS NOT NULL)::BIGINT AS n_replies
            FROM telegram.messages
            """).fetchone()
        assert row is not None
        inv = {
            "n_events": row[0],
            "n_messages": row[1],
            "n_chats": row[2],
            "first_day": row[3],
            "last_day": row[4],
            "n_photos": row[5],
            "n_replies": row[6],
        }
        inv["summary"] = (
            f"telegram.messages: {inv['n_events']:,} rows "
            f"({inv['n_chats']} chats) | "
            f"{inv['first_day']} → {inv['last_day']} | "
            f"photos {inv['n_photos']:,} | "
            f"replies {inv['n_replies']:,}"
        )
        return inv
