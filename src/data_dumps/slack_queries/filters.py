"""Filter state and DuckDB queries for the Slack Marimo dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util

HUMAN_SUBTYPES = ("message", "thread_broadcast")


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    channel_ids: list[str] = field(default_factory=list)
    user_ids: list[str] = field(default_factory=list)
    include_bots: bool = False
    include_system: bool = False
    include_archived: bool = True

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        chip = query_util.year_chip(self.year_start, self.year_end)
        if chip is not None:
            chips.append(chip)
        if self.channel_ids:
            chips.append(("channels", f"{len(self.channel_ids)} channel(s)"))
        if self.user_ids:
            chips.append(("people", f"{len(self.user_ids)} person(s)"))
        if self.include_bots:
            chips.append(("include_bots", "incl. bots"))
        if self.include_system:
            chips.append(("include_system", "incl. system events"))
        if not self.include_archived:
            chips.append(("archived", "active channels only"))
        return chips


def _where(f: FilterState, alias: str = "m") -> tuple[str, list[Any]]:
    p = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list[Any] = []
    query_util.append_year_clause(clauses, params, alias, f.year_start, f.year_end)
    if f.channel_ids:
        ph = ", ".join("?" for _ in f.channel_ids)
        clauses.append(f"{p}channel_id IN ({ph})")
        params.extend(f.channel_ids)
    if f.user_ids:
        ph = ", ".join("?" for _ in f.user_ids)
        clauses.append(f"{p}user_id IN ({ph})")
        params.extend(f.user_ids)
    if not f.include_bots:
        clauses.append(f"NOT {p}is_bot")
    if not f.include_system:
        ph = ", ".join("?" for _ in HUMAN_SUBTYPES)
        clauses.append(f"{p}subtype IN ({ph})")
        params.extend(HUMAN_SUBTYPES)
    if not f.include_archived:
        clauses.append("NOT c.is_archived")
    return (" AND ".join(clauses) if clauses else "1=1"), params


def _from_join() -> str:
    return """
        FROM slack.messages m
        JOIN slack.channels c ON c.channel_id = m.channel_id
    """


def _query_df(
    conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def _ym(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty and {"year", "month"} <= set(df.columns):
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT, max(year)::INT,
            min(ts_utc)::DATE, max(ts_utc)::DATE
        FROM slack.messages
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2018, 2025
    channels = conn.execute("""
        SELECT channel_id, name, kind, is_archived, coalesce(n_messages, 0) AS n
        FROM slack.channels
        ORDER BY n DESC, name
        """).fetchall()
    people = conn.execute("""
        SELECT
            u.user_id,
            coalesce(u.real_name, u.display_name, u.handle, u.user_id) AS name,
            u.handle,
            u.deleted,
            count(m.ts)::BIGINT AS n
        FROM slack.users u
        LEFT JOIN slack.messages m
          ON m.user_id = u.user_id AND NOT m.is_bot
         AND m.subtype IN ('message', 'thread_broadcast')
        WHERE NOT u.is_bot
        GROUP BY 1, 2, 3, 4
        HAVING count(m.ts) > 0
        ORDER BY n DESC, name
        """).fetchall()
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "channels": [
            {
                "channel_id": r[0],
                "name": r[1],
                "kind": r[2],
                "is_archived": r[3],
                "messages": r[4],
            }
            for r in channels
        ],
        "people": [
            {
                "user_id": r[0],
                "name": r[1],
                "handle": r[2],
                "deleted": r[3],
                "messages": r[4],
            }
            for r in people
        ],
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    channel_ids: list[str] | None = None,
    user_ids: list[str] | None = None,
    include_bots: bool = False,
    include_system: bool = False,
    include_archived: bool = True,
) -> FilterState:
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    return FilterState(
        year_start=ys,
        year_end=ye,
        channel_ids=list(channel_ids or []),
        user_ids=list(user_ids or []),
        include_bots=include_bots,
        include_system=include_system,
        include_archived=include_archived,
    )
