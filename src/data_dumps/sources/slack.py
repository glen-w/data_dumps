"""Slack workspace export (zip or extracted folder) → DuckDB.

The export is ``users.json`` + ``channels.json`` at the root plus one folder per
channel holding ``YYYY-MM-DD.json`` daily message files. File-conversation
folders (``FC:<FILEID>:<title>``) are landed as channels of kind
``file_conversation``. Other top-level files (canvases, lists, integration
logs, huddles) are skipped.

Loading streams daily files straight out of the zip; only ``users.json`` and
``channels.json`` are copied under ``raw/slack/``.

Privacy: display names and message text are kept; emails, phones, Skype
handles and avatar URLs are dropped at ingest.

Loader / user-mapping / text-cleaning logic was ported from the standalone
``slack analysis`` project (``SlackDataLoader``, ``BaseAnalyzer.get_user_name``,
``TextProcessor.clean_text``) and extended to resolve mentions instead of
stripping them.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_dumps.paths import raw_dir

LOCAL_TZ = ZoneInfo("Europe/Paris")
USERS_JSON = "users.json"
CHANNELS_JSON = "channels.json"
DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
FC_DIR_RE = re.compile(r"^FC:([A-Z0-9]+):(.*)$")
MENTION_RE = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")
CHANNEL_REF_RE = re.compile(r"<#([A-Z0-9]+)\|([^>]*)>")
SPECIAL_RE = re.compile(r"<!(channel|here|everyone)(?:\|[^>]*)?>")
LINK_RE = re.compile(r"<((?:https?|mailto)[^>|]*)(?:\|([^>]*))?>")
HUMAN_SUBTYPES = frozenset({"message", "thread_broadcast"})

SLACK_TABLES = [
    "slack.users",
    "slack.channels",
    "slack.channel_members",
    "slack.messages",
    "slack.reactions",
    "slack.mentions",
    "slack.files",
]

USER_COLS = [
    "user_id",
    "handle",
    "real_name",
    "display_name",
    "title",
    "tz",
    "is_bot",
    "is_app_user",
    "deleted",
    "is_admin",
    "is_owner",
    "is_restricted",
]
CHANNEL_COLS = [
    "channel_id",
    "name",
    "kind",
    "created_utc",
    "creator_id",
    "is_archived",
    "is_general",
    "n_members",
    "purpose",
    "topic",
]
MESSAGE_COLS = [
    "channel_id",
    "channel_name",
    "ts",
    "ts_utc",
    "ts_local",
    "user_id",
    "user_name",
    "subtype",
    "is_bot",
    "bot_id",
    "bot_name",
    "text",
    "text_len",
    "thread_ts",
    "is_thread_root",
    "is_reply",
    "parent_user_id",
    "reply_count",
    "reply_users_count",
    "latest_reply_utc",
    "edited",
    "n_files",
    "n_attachments",
    "n_reactions",
    "n_mentions",
    "has_link",
    "year",
    "month",
]
REACTION_COLS = ["channel_id", "ts", "emoji", "user_id"]
MENTION_COLS = ["channel_id", "ts", "mentioned_user_id"]
FILE_COLS = ["channel_id", "ts", "file_id", "name", "filetype", "size_bytes", "mode"]


# --------------------------------------------------------------------------- #
# Helpers


def _fix_zip_name(info: zipfile.ZipInfo) -> str:
    """Undo cp437 mojibake for entries written without the UTF-8 flag."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def _ts_pair(ts: str | float) -> tuple[datetime, datetime]:
    """Slack ``ts`` (``'1617867056.011100'``) → naive UTC and Europe/Paris."""
    ts_utc = datetime.fromtimestamp(float(ts), tz=UTC)
    ts_local = ts_utc.astimezone(LOCAL_TZ)
    return ts_utc.replace(tzinfo=None), ts_local.replace(tzinfo=None)


def _display_name(user: dict[str, Any]) -> str:
    """real_name → display_name → handle → id (ported from BaseAnalyzer)."""
    profile = user.get("profile") or {}
    for cand in (
        user.get("real_name"),
        profile.get("real_name"),
        profile.get("display_name"),
        user.get("name"),
    ):
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    return str(user.get("id") or "unknown")


def clean_text(text: str | None, names: dict[str, str]) -> tuple[str | None, list[str]]:
    """Resolve Slack markup to readable text; return (text, mentioned user ids)."""
    if not text:
        return None, []
    mentioned = MENTION_RE.findall(text)

    def _mention(m: re.Match[str]) -> str:
        uid = m.group(1)
        return "@" + names.get(uid, uid)

    out = MENTION_RE.sub(_mention, text)
    out = CHANNEL_REF_RE.sub(lambda m: "#" + (m.group(2) or m.group(1)), out)
    out = SPECIAL_RE.sub(lambda m: "@" + m.group(1), out)
    out = LINK_RE.sub(lambda m: m.group(2) or m.group(1), out)
    out = out.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return out, mentioned


def _parse_channel_dir(name: str) -> tuple[str | None, str, str]:
    """Return (channel_id_if_fc, display_name, kind) for a channel folder."""
    m = FC_DIR_RE.match(name)
    if m:
        title = m.group(2).strip() or name
        return m.group(1), title, "file_conversation"
    return None, name, "channel"


class _ExportReader:
    """Uniform access to a zip or extracted folder."""

    def __init__(self, path: Path):
        self.path = path
        self._zf: zipfile.ZipFile | None = None
        self._entries: list[tuple[str, zipfile.ZipInfo]] = []
        if path.is_file():
            self._zf = zipfile.ZipFile(path)
            self._entries = [
                (_fix_zip_name(i), i) for i in self._zf.infolist() if not i.is_dir()
            ]

    def close(self) -> None:
        if self._zf is not None:
            self._zf.close()

    def read_json(self, relname: str) -> Any:
        if self._zf is not None:
            for name, info in self._entries:
                if name == relname:
                    return json.loads(self._zf.read(info))
            raise FileNotFoundError(relname)
        with (self.path / relname).open(encoding="utf-8") as fh:
            return json.load(fh)

    def copy_to(self, relname: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self._zf is not None:
            for name, info in self._entries:
                if name == relname:
                    dest.write_bytes(self._zf.read(info))
                    return
            raise FileNotFoundError(relname)
        shutil.copy2(self.path / relname, dest)

    def daily_files(self) -> Iterator[tuple[str, str, Any]]:
        """Yield (channel_dir, day, payload) for every daily message file."""
        if self._zf is not None:
            for name, info in self._entries:
                parts = name.split("/")
                if len(parts) != 2 or not DAILY_RE.match(parts[1]):
                    continue
                try:
                    payload = json.loads(self._zf.read(info))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                yield parts[0], parts[1][:-5], payload
            return
        for sub in sorted(p for p in self.path.iterdir() if p.is_dir()):
            for file in sorted(sub.iterdir()):
                if not DAILY_RE.match(file.name):
                    continue
                try:
                    with file.open(encoding="utf-8") as fh:
                        payload = json.load(fh)
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    continue
                yield sub.name, file.name[:-5], payload


def _root_has_export(names: set[str]) -> bool:
    return USERS_JSON in names and CHANNELS_JSON in names


# --------------------------------------------------------------------------- #
# Source


class SlackSource:
    name = "slack"

    def detect(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    names = {_fix_zip_name(i) for i in zf.infolist()}
            except (OSError, zipfile.BadZipFile):
                return False
            return _root_has_export(names)
        if path.is_dir():
            return (path / USERS_JSON).is_file() and (path / CHANNELS_JSON).is_file()
        return False

    def tables(self) -> list[str]:
        return list(SLACK_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        path = path.resolve()
        reader = _ExportReader(path)
        try:
            dest = raw_dir("slack")
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            reader.copy_to(USERS_JSON, dest / USERS_JSON)
            reader.copy_to(CHANNELS_JSON, dest / CHANNELS_JSON)
            (dest / "export_root.txt").write_text(str(path) + "\n", encoding="utf-8")

            users_raw = reader.read_json(USERS_JSON)
            channels_raw = reader.read_json(CHANNELS_JSON)
            users_df, names, bot_ids = _users_frame(users_raw)
            channels_df, members_df, name_to_id = _channels_frame(channels_raw)
            msgs, reacts, mentions, files, extra_channels = _message_frames(
                reader, names, bot_ids, name_to_id
            )
            if extra_channels:
                channels_df = pd.concat(
                    [channels_df, pd.DataFrame(extra_channels, columns=CHANNEL_COLS)],
                    ignore_index=True,
                )
        finally:
            reader.close()

        # Nullable ints / datetimes so DuckDB sees NULL rather than NaN/object.
        channels_df["n_members"] = channels_df["n_members"].astype("Int64")
        channels_df["created_utc"] = pd.to_datetime(channels_df["created_utc"])
        msgs["latest_reply_utc"] = pd.to_datetime(msgs["latest_reply_utc"])
        files["size_bytes"] = files["size_bytes"].astype("Int64")

        conn.execute("CREATE SCHEMA IF NOT EXISTS slack")
        for table in (
            "files",
            "mentions",
            "reactions",
            "messages",
            "channel_members",
            "channels",
            "users",
        ):
            conn.execute(f"DROP TABLE IF EXISTS slack.{table}")

        conn.execute("""
            CREATE TABLE slack.users (
                user_id VARCHAR,
                handle VARCHAR,
                real_name VARCHAR,
                display_name VARCHAR,
                title VARCHAR,
                tz VARCHAR,
                is_bot BOOLEAN,
                is_app_user BOOLEAN,
                deleted BOOLEAN,
                is_admin BOOLEAN,
                is_owner BOOLEAN,
                is_restricted BOOLEAN
            )
            """)
        conn.execute("""
            CREATE TABLE slack.channels (
                channel_id VARCHAR,
                name VARCHAR,
                kind VARCHAR,
                created_utc TIMESTAMP,
                creator_id VARCHAR,
                is_archived BOOLEAN,
                is_general BOOLEAN,
                n_members INTEGER,
                purpose VARCHAR,
                topic VARCHAR,
                first_ts TIMESTAMP,
                last_ts TIMESTAMP,
                n_messages BIGINT
            )
            """)
        conn.execute("""
            CREATE TABLE slack.channel_members (
                channel_id VARCHAR,
                user_id VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE slack.messages (
                channel_id VARCHAR,
                channel_name VARCHAR,
                ts VARCHAR,
                ts_utc TIMESTAMP,
                ts_local TIMESTAMP,
                user_id VARCHAR,
                user_name VARCHAR,
                subtype VARCHAR,
                is_bot BOOLEAN,
                bot_id VARCHAR,
                bot_name VARCHAR,
                text VARCHAR,
                text_len INTEGER,
                thread_ts VARCHAR,
                is_thread_root BOOLEAN,
                is_reply BOOLEAN,
                parent_user_id VARCHAR,
                reply_count INTEGER,
                reply_users_count INTEGER,
                latest_reply_utc TIMESTAMP,
                edited BOOLEAN,
                n_files INTEGER,
                n_attachments INTEGER,
                n_reactions INTEGER,
                n_mentions INTEGER,
                has_link BOOLEAN,
                year INTEGER,
                month INTEGER
            )
            """)
        conn.execute("""
            CREATE TABLE slack.reactions (
                channel_id VARCHAR,
                ts VARCHAR,
                emoji VARCHAR,
                user_id VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE slack.mentions (
                channel_id VARCHAR,
                ts VARCHAR,
                mentioned_user_id VARCHAR
            )
            """)
        conn.execute("""
            CREATE TABLE slack.files (
                channel_id VARCHAR,
                ts VARCHAR,
                file_id VARCHAR,
                name VARCHAR,
                filetype VARCHAR,
                size_bytes BIGINT,
                mode VARCHAR
            )
            """)

        for tmp, df, table in (
            ("_sk_users", users_df, "users"),
            ("_sk_channels", channels_df, "channels"),
            ("_sk_members", members_df, "channel_members"),
            ("_sk_messages", msgs, "messages"),
            ("_sk_reactions", reacts, "reactions"),
            ("_sk_mentions", mentions, "mentions"),
            ("_sk_files", files, "files"),
        ):
            conn.register(tmp, df)
            conn.execute(f"INSERT INTO slack.{table} BY NAME SELECT * FROM {tmp}")
            conn.unregister(tmp)

        conn.execute("""
            UPDATE slack.channels c
            SET first_ts = s.first_ts, last_ts = s.last_ts, n_messages = s.n
            FROM (
                SELECT channel_id, min(ts_utc) AS first_ts, max(ts_utc) AS last_ts,
                       count(*) AS n
                FROM slack.messages GROUP BY 1
            ) s
            WHERE c.channel_id = s.channel_id
            """)

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        row = conn.execute("""
            SELECT
                count(*)::BIGINT AS n_events,
                count(*) FILTER (
                    WHERE NOT is_bot AND subtype IN ('message', 'thread_broadcast')
                )::BIGINT AS n_human,
                count(DISTINCT channel_id)::BIGINT AS n_channels,
                count(DISTINCT user_id) FILTER (WHERE NOT is_bot)::BIGINT AS n_people,
                min(ts_utc)::DATE AS first_day,
                max(ts_utc)::DATE AS last_day,
                count(*) FILTER (WHERE is_reply)::BIGINT AS n_replies
            FROM slack.messages
            """).fetchone()
        assert row is not None
        n_react = conn.execute("SELECT count(*) FROM slack.reactions").fetchone()
        inv = {
            "n_events": row[0],
            "n_human_messages": row[1],
            "n_channels": row[2],
            "n_people": row[3],
            "first_day": row[4],
            "last_day": row[5],
            "n_replies": row[6],
            "n_reactions": n_react[0] if n_react else 0,
        }
        inv["summary"] = (
            f"slack.messages: {inv['n_events']:,} rows "
            f"({inv['n_human_messages']:,} human, {inv['n_channels']} channels, "
            f"{inv['n_people']} people) | "
            f"{inv['first_day']} → {inv['last_day']} | "
            f"replies {inv['n_replies']:,} | reactions {inv['n_reactions']:,}"
        )
        return inv


# --------------------------------------------------------------------------- #
# Frame builders


def _users_frame(
    users_raw: list[dict[str, Any]],
) -> tuple[pd.DataFrame, dict[str, str], set[str]]:
    rows: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    bot_ids: set[str] = set()
    for u in users_raw or []:
        uid = u.get("id")
        if not uid:
            continue
        profile = u.get("profile") or {}
        is_bot = bool(u.get("is_bot")) or uid == "USLACKBOT"
        if is_bot:
            bot_ids.add(uid)
        names[uid] = _display_name(u)
        rows.append(
            {
                "user_id": uid,
                "handle": u.get("name"),
                "real_name": u.get("real_name") or profile.get("real_name"),
                "display_name": profile.get("display_name") or None,
                "title": profile.get("title") or None,
                "tz": u.get("tz"),
                "is_bot": is_bot,
                "is_app_user": bool(u.get("is_app_user")),
                "deleted": bool(u.get("deleted")),
                "is_admin": bool(u.get("is_admin")),
                "is_owner": bool(u.get("is_owner")),
                "is_restricted": bool(u.get("is_restricted")),
            }
        )
    df = pd.DataFrame(rows, columns=USER_COLS)
    return df, names, bot_ids


def _channels_frame(
    channels_raw: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    rows: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    name_to_id: dict[str, str] = {}
    for c in channels_raw or []:
        cid = c.get("id")
        cname = c.get("name")
        if not cid or not cname:
            continue
        name_to_id[cname] = cid
        created = c.get("created")
        members = c.get("members") or []
        rows.append(
            {
                "channel_id": cid,
                "name": cname,
                "kind": "channel",
                "created_utc": (
                    datetime.fromtimestamp(int(created), tz=UTC).replace(tzinfo=None)
                    if created
                    else None
                ),
                "creator_id": c.get("creator"),
                "is_archived": bool(c.get("is_archived")),
                "is_general": bool(c.get("is_general")),
                "n_members": len(members),
                "purpose": ((c.get("purpose") or {}).get("value") or None),
                "topic": ((c.get("topic") or {}).get("value") or None),
            }
        )
        for uid in members:
            member_rows.append({"channel_id": cid, "user_id": uid})
    channels_df = pd.DataFrame(rows, columns=CHANNEL_COLS)
    members_df = pd.DataFrame(member_rows, columns=["channel_id", "user_id"])
    return channels_df, members_df, name_to_id


def _message_frames(
    reader: _ExportReader,
    names: dict[str, str],
    bot_ids: set[str],
    name_to_id: dict[str, str],
) -> tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, Any]]
]:
    msg_rows: list[dict[str, Any]] = []
    react_rows: list[dict[str, Any]] = []
    mention_rows: list[dict[str, Any]] = []
    file_rows: list[dict[str, Any]] = []
    extra_channels: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str]] = set()

    for dir_name, _day, payload in reader.daily_files():
        if not isinstance(payload, list):
            continue
        fc_id, display, kind = _parse_channel_dir(dir_name)
        if fc_id is not None:
            channel_id = fc_id
            if channel_id not in extra_channels:
                extra_channels[channel_id] = {
                    "channel_id": channel_id,
                    "name": display,
                    "kind": kind,
                    "created_utc": None,
                    "creator_id": None,
                    "is_archived": False,
                    "is_general": False,
                    "n_members": None,
                    "purpose": None,
                    "topic": None,
                }
        else:
            channel_id = name_to_id.get(dir_name, dir_name)
            if dir_name not in name_to_id:
                if channel_id not in extra_channels:
                    extra_channels[channel_id] = {
                        "channel_id": channel_id,
                        "name": display,
                        "kind": "channel",
                        "created_utc": None,
                        "creator_id": None,
                        "is_archived": False,
                        "is_general": False,
                        "n_members": None,
                        "purpose": None,
                        "topic": None,
                    }

        for m in payload:
            if not isinstance(m, dict) or m.get("type") != "message":
                continue
            ts = m.get("ts")
            if not ts:
                continue
            ts = str(ts)
            key = (channel_id, ts)
            if key in seen:
                continue
            seen.add(key)
            try:
                ts_utc, ts_local = _ts_pair(ts)
            except (ValueError, OverflowError, OSError):
                continue

            uid = m.get("user")
            subtype = m.get("subtype") or "message"
            bot_id = m.get("bot_id")
            is_bot = bool(bot_id) or subtype == "bot_message" or uid in bot_ids
            profile = m.get("user_profile") or {}
            user_name = (
                names.get(uid)
                if uid in names
                else (
                    profile.get("real_name")
                    or profile.get("display_name")
                    or m.get("username")
                    or uid
                )
            )
            bot_name = m.get("username") or ((m.get("bot_profile") or {}).get("name"))

            text, mentioned = clean_text(m.get("text"), names)
            thread_ts = m.get("thread_ts")
            reply_count = m.get("reply_count")
            files = m.get("files") or []
            attachments = m.get("attachments") or []
            reactions = m.get("reactions") or []
            latest_reply = m.get("latest_reply")
            latest_reply_utc = None
            if latest_reply:
                try:
                    latest_reply_utc = _ts_pair(latest_reply)[0]
                except (ValueError, OverflowError, OSError):
                    latest_reply_utc = None

            msg_rows.append(
                {
                    "channel_id": channel_id,
                    "channel_name": display,
                    "ts": ts,
                    "ts_utc": ts_utc,
                    "ts_local": ts_local,
                    "user_id": uid,
                    "user_name": user_name,
                    "subtype": subtype,
                    "is_bot": is_bot,
                    "bot_id": bot_id,
                    "bot_name": bot_name if is_bot else None,
                    "text": text,
                    "text_len": len(text) if text else 0,
                    "thread_ts": thread_ts,
                    "is_thread_root": bool(reply_count),
                    "is_reply": bool(thread_ts) and thread_ts != ts,
                    "parent_user_id": m.get("parent_user_id"),
                    "reply_count": int(reply_count) if reply_count else 0,
                    "reply_users_count": int(m.get("reply_users_count") or 0),
                    "latest_reply_utc": latest_reply_utc,
                    "edited": bool(m.get("edited")),
                    "n_files": len(files),
                    "n_attachments": len(attachments),
                    "n_reactions": sum(int(r.get("count") or 0) for r in reactions),
                    "n_mentions": len(mentioned),
                    "has_link": bool(LINK_RE.search(m.get("text") or "")),
                    "year": ts_local.year,
                    "month": ts_local.month,
                }
            )
            for r in reactions:
                emoji = r.get("name")
                if not emoji:
                    continue
                users = r.get("users") or []
                if users:
                    for ruid in users:
                        react_rows.append(
                            {
                                "channel_id": channel_id,
                                "ts": ts,
                                "emoji": emoji,
                                "user_id": ruid,
                            }
                        )
                else:
                    for _ in range(int(r.get("count") or 1)):
                        react_rows.append(
                            {
                                "channel_id": channel_id,
                                "ts": ts,
                                "emoji": emoji,
                                "user_id": None,
                            }
                        )
            for muid in mentioned:
                mention_rows.append(
                    {"channel_id": channel_id, "ts": ts, "mentioned_user_id": muid}
                )
            for f in files:
                if not isinstance(f, dict):
                    continue
                file_rows.append(
                    {
                        "channel_id": channel_id,
                        "ts": ts,
                        "file_id": f.get("id"),
                        "name": f.get("name") or f.get("title"),
                        "filetype": f.get("filetype"),
                        "size_bytes": f.get("size"),
                        "mode": f.get("mode"),
                    }
                )

    msgs = pd.DataFrame(msg_rows, columns=MESSAGE_COLS)
    reacts = pd.DataFrame(react_rows, columns=REACTION_COLS)
    mentions = pd.DataFrame(mention_rows, columns=MENTION_COLS)
    files_df = pd.DataFrame(file_rows, columns=FILE_COLS)
    return msgs, reacts, mentions, files_df, list(extra_channels.values())
