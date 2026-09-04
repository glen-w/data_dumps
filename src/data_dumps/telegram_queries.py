"""Filter state and DuckDB queries for the Telegram Marimo dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd


@dataclass
class FilterState:
    """One filter state drives every Telegram dashboard query."""

    year_start: int | None = None
    year_end: int | None = None
    chat_types: list[str] = field(default_factory=list)
    chat_ids: list[int] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    media_kinds: list[str] = field(default_factory=list)
    chat_name: str | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        for t in self.chat_types:
            chips.append(("chat_type", f"type={t}"))
        if self.chat_name:
            chips.append(("chat_name", f"chat: {self.chat_name}"))
        for eid in self.chat_ids:
            chips.append(("chat_id", f"chat_id={eid}"))
        for e in self.event_types:
            chips.append(("event_type", f"event={e}"))
        for m in self.media_kinds:
            chips.append(("media_kind", f"media={m}"))
        return chips

    def clear_field(self, field_name: str) -> None:
        if field_name == "year_range":
            self.year_start = None
            self.year_end = None
        elif field_name == "chat_type":
            self.chat_types = []
        elif field_name == "chat_id":
            self.chat_ids = []
            self.chat_name = None
        elif field_name == "chat_name":
            self.chat_name = None
        elif field_name == "event_type":
            self.event_types = []
        elif field_name == "media_kind":
            self.media_kinds = []


def _where_and_params(
    f: FilterState,
    *,
    table_alias: str = "m",
) -> tuple[str, list[Any]]:
    prefix = f"{table_alias}." if table_alias else ""
    clauses: list[str] = []
    params: list[Any] = []

    if f.year_start is not None:
        clauses.append(f"{prefix}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{prefix}year <= ?")
        params.append(f.year_end)
    if f.chat_types:
        placeholders = ", ".join("?" for _ in f.chat_types)
        clauses.append(f"c.type IN ({placeholders})")
        params.extend(f.chat_types)
    if f.chat_ids:
        placeholders = ", ".join("?" for _ in f.chat_ids)
        clauses.append(f"{prefix}chat_id IN ({placeholders})")
        params.extend(f.chat_ids)
    if f.chat_name:
        clauses.append("c.name = ?")
        params.append(f.chat_name)
    if f.event_types:
        placeholders = ", ".join("?" for _ in f.event_types)
        clauses.append(f"{prefix}event_type IN ({placeholders})")
        params.extend(f.event_types)
    if f.media_kinds:
        placeholders = ", ".join("?" for _ in f.media_kinds)
        clauses.append(f"{prefix}media_kind IN ({placeholders})")
        params.extend(f.media_kinds)

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def _from_join() -> str:
    return """
        FROM telegram.messages m
        JOIN telegram.chats c ON c.chat_id = m.chat_id
    """


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any],
) -> pd.DataFrame:
    return conn.execute(sql, params).df()


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT AS min_year,
            max(year)::INT AS max_year,
            min(ts_utc)::DATE AS first_day,
            max(ts_utc)::DATE AS last_day
        FROM telegram.messages
        """).fetchone()
    assert row is not None
    chat_types = conn.execute(
        "SELECT DISTINCT type FROM telegram.chats ORDER BY 1"
    ).fetchall()
    event_types = conn.execute(
        "SELECT DISTINCT event_type FROM telegram.messages ORDER BY 1"
    ).fetchall()
    media_kinds = conn.execute(
        "SELECT DISTINCT media_kind FROM telegram.messages ORDER BY 1"
    ).fetchall()
    chats = conn.execute(
        "SELECT chat_id, name FROM telegram.chats ORDER BY name"
    ).fetchall()
    return {
        "min_year": row[0],
        "max_year": row[1],
        "first_day": row[2],
        "last_day": row[3],
        "chat_types": [r[0] for r in chat_types],
        "event_types": [r[0] for r in event_types],
        "media_kinds": [r[0] for r in media_kinds],
        "chats": [{"chat_id": r[0], "name": r[1]} for r in chats],
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    chat_types: list[str],
    event_types: list[str],
    media_kinds: list[str],
    chat_name: str | None = None,
    chat_ids: list[int] | None = None,
) -> FilterState:
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    return FilterState(
        year_start=ys,
        year_end=ye,
        chat_types=chat_types,
        event_types=event_types,
        media_kinds=media_kinds,
        chat_name=chat_name,
        chat_ids=chat_ids or [],
    )


def scoreboard(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            count(*)::BIGINT AS events,
            count(*) FILTER (WHERE m.event_type = 'message')::BIGINT AS messages,
            count(DISTINCT m.chat_id)::BIGINT AS chats,
            count(*) FILTER (WHERE m.media_kind <> 'none')::BIGINT AS with_media,
            count(*) FILTER (WHERE m.reply_to_message_id IS NOT NULL)::BIGINT AS replies,
            min(m.ts_utc)::DATE AS first_day,
            max(m.ts_utc)::DATE AS last_day
        {_from_join()}
        WHERE {where}
    """
    return _query_df(conn, sql, params)


def monthly_messages(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            m.year,
            m.month,
            count(*)::BIGINT AS events
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    df = _query_df(conn, sql, params)
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def messages_by_chat(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.append(limit)
    sql = f"""
        SELECT
            c.chat_id,
            c.name AS chat_name,
            c.type AS chat_type,
            count(*)::BIGINT AS events,
            count(*) FILTER (WHERE m.event_type = 'message')::BIGINT AS messages
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2, 3
        ORDER BY events DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def messages_by_chat_type(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            c.type AS chat_type,
            count(*)::BIGINT AS events
        {_from_join()}
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
    """
    return _query_df(conn, sql, params)


def media_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            m.media_kind,
            count(*)::BIGINT AS events
        {_from_join()}
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
    """
    return _query_df(conn, sql, params)


def circadian_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            dayofweek(m.ts_local) AS dow,
            hour(m.ts_local) AS hour,
            count(*)::BIGINT AS events
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    return _query_df(conn, sql, params)
