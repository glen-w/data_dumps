"""Thunderbird profile Gloda index → DuckDB (metadata aggregation only).

Reads ``global-messages-db.sqlite`` via an ephemeral SQLite backup snapshot.
Does not copy, move, or edit mail directories / mbox files. Message bodies are
never written to the warehouse.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from data_dumps.sources.thunderbird_gloda import (
    extract_folders,
    extract_messages,
    identities_from_env,
    looks_like_gloda_path,
    parse_prefs_identities,
    resolve_gloda_paths,
    snapshot_gloda,
)

TB_TABLES = [
    "thunderbird.accounts",
    "thunderbird.folders",
    "thunderbird.messages",
    "thunderbird.participants",
    "thunderbird.signals",
]


class ThunderbirdSource:
    name = "thunderbird"

    def __init__(self, extra_identities: set[str] | None = None) -> None:
        # Mutable set; ingest CLI may extend via ``source.identities |= …``.
        self.identities = {e.lower() for e in (extra_identities or set())}

    def detect(self, path: Path) -> bool:
        return looks_like_gloda_path(path)

    def tables(self) -> list[str]:
        return list(TB_TABLES)

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        gloda_path, profile_dir = resolve_gloda_paths(path)

        identities: set[str] = set(self.identities)
        identities |= identities_from_env()
        prefs_path = (profile_dir / "prefs.js") if profile_dir else None
        prefs_rows = parse_prefs_identities(prefs_path) if prefs_path else []
        for row in prefs_rows:
            email = (row.get("email") or "").strip().lower()
            if email:
                identities.add(email)

        snap: Path | None = None
        try:
            snap = snapshot_gloda(gloda_path)
            sconn = sqlite3.connect(str(snap))
            try:
                folders = extract_folders(sconn)
                folder_meta = {int(f["folder_id"]): f for f in folders}
                messages, participants, signals = extract_messages(
                    sconn, identities=identities, folder_meta=folder_meta
                )
            finally:
                sconn.close()
        finally:
            if snap is not None:
                snap.unlink(missing_ok=True)

        # Drop deleted; keep warehouse lean for stats.
        messages = [m for m in messages if not m.get("deleted")]
        keep_ids = {m["gloda_id"] for m in messages}
        participants = [p for p in participants if p["message_id"] in keep_ids]
        signals = [s for s in signals if s["message_id"] in keep_ids]

        # Convenience columns for dashboard filters (Rome local calendar day).
        for m in messages:
            dl = m.get("date_local")
            m["local_date"] = dl.date() if dl is not None else None
            m["weekday"] = m.get("dow")  # alias for circadian queries

        accounts_df = pd.DataFrame(prefs_rows)
        if accounts_df.empty:
            keys = sorted({f["account_key"] for f in folders if f.get("account_key")})
            accounts_df = pd.DataFrame(
                [
                    {
                        "account_key": "",
                        "identity_key": "",
                        "email": e,
                        "display_name": "",
                        "server_type": None,
                        "hostname": None,
                        "label": None,
                    }
                    for e in sorted(identities)
                ]
                if identities
                else [
                    {
                        "account_key": k,
                        "identity_key": "",
                        "email": "",
                        "display_name": k or "",
                        "server_type": None,
                        "hostname": None,
                        "label": k,
                    }
                    for k in keys
                ]
            )

        folders_df = pd.DataFrame(folders)
        messages_df = pd.DataFrame(messages)
        participants_df = pd.DataFrame(participants)
        signals_df = pd.DataFrame(signals)

        if folders_df.empty:
            folders_df = pd.DataFrame(
                columns=["folder_id", "name", "folder_uri", "account_key"]
            )
        if messages_df.empty:
            messages_df = pd.DataFrame(
                columns=[
                    "gloda_id",
                    "date_utc",
                    "date_local",
                    "local_date",
                    "year",
                    "month",
                    "day",
                    "hour",
                    "dow",
                    "weekday",
                    "folder_id",
                    "conversation_id",
                    "header_message_id",
                    "subject",
                    "attachment_names",
                    "has_attachment",
                    "deleted",
                    "starred",
                    "read",
                    "replied",
                    "forwarded",
                    "is_encrypted",
                    "from_me",
                    "to_me",
                    "direction",
                    "from_raw",
                    "from_addr",
                    "from_name",
                    "from_domain",
                ]
            )
        if participants_df.empty:
            participants_df = pd.DataFrame(
                columns=["message_id", "role", "addr", "domain", "display_name"]
            )
        if signals_df.empty:
            signals_df = pd.DataFrame(
                columns=["message_id", "kind", "confidence", "detail"]
            )

        conn.execute("CREATE SCHEMA IF NOT EXISTS thunderbird")
        for table in (
            "accounts",
            "folders",
            "messages",
            "participants",
            "signals",
        ):
            conn.execute(f"DROP TABLE IF EXISTS thunderbird.{table}")

        conn.register("_tb_accounts", accounts_df)
        conn.execute("CREATE TABLE thunderbird.accounts AS SELECT * FROM _tb_accounts")
        conn.unregister("_tb_accounts")

        conn.register("_tb_folders", folders_df)
        conn.execute("CREATE TABLE thunderbird.folders AS SELECT * FROM _tb_folders")
        conn.unregister("_tb_folders")

        conn.register("_tb_messages", messages_df)
        conn.execute("CREATE TABLE thunderbird.messages AS SELECT * FROM _tb_messages")
        conn.unregister("_tb_messages")

        conn.register("_tb_participants", participants_df)
        conn.execute(
            "CREATE TABLE thunderbird.participants AS SELECT * FROM _tb_participants"
        )
        conn.unregister("_tb_participants")

        conn.register("_tb_signals", signals_df)
        conn.execute("CREATE TABLE thunderbird.signals AS SELECT * FROM _tb_signals")
        conn.unregister("_tb_signals")

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        n = conn.execute("SELECT count(*) FROM thunderbird.messages").fetchone()
        n_folders = conn.execute("SELECT count(*) FROM thunderbird.folders").fetchone()
        n_signals = conn.execute("SELECT count(*) FROM thunderbird.signals").fetchone()
        span = conn.execute(
            "SELECT min(local_date), max(local_date) FROM thunderbird.messages"
        ).fetchone()
        dirs = conn.execute("""
            SELECT direction, count(*)::BIGINT
            FROM thunderbird.messages
            GROUP BY 1
            ORDER BY 1
            """).fetchall()
        n_msg = n[0] if n else 0
        first = span[0] if span else None
        last = span[1] if span else None
        dir_s = ", ".join(f"{d}={c}" for d, c in dirs) if dirs else "none"
        summary = (
            f"thunderbird.messages={n_msg} folders={n_folders[0] if n_folders else 0} "
            f"signals={n_signals[0] if n_signals else 0} span={first}→{last} ({dir_s})"
        )
        return {
            "n_messages": n_msg,
            "n_folders": n_folders[0] if n_folders else 0,
            "n_signals": n_signals[0] if n_signals else 0,
            "first_day": first,
            "last_day": last,
            "summary": summary,
        }
