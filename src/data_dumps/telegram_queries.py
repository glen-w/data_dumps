"""Filter state and DuckDB queries for the Telegram Marimo dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

PEOPLE_CHAT_TYPES = [
    "personal_chat",
    "private_group",
    "private_supergroup",
    "saved_messages",
]

BOT_CHAT_TYPES = frozenset({"bot_chat"})

# Collective chats controlled by the Telegram "Show groups" toggle (incl. channels).
GROUP_CHAT_TYPES = frozenset(
    {
        "private_group",
        "private_supergroup",
        "public_group",
        "public_supergroup",
        "private_channel",
        "public_channel",
        "channel",
    }
)


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
    include_bots: bool = False
    include_groups: bool = False

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
        if self.include_bots:
            chips.append(("include_bots", "incl. bots"))
        if self.include_groups:
            chips.append(("include_groups", "incl. groups"))
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
        elif field_name == "include_bots":
            self.include_bots = False
        elif field_name == "include_groups":
            self.include_groups = False


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

    excluded_types: list[str] = []
    if not f.include_bots:
        excluded_types.extend(sorted(BOT_CHAT_TYPES))
    if not f.include_groups:
        excluded_types.extend(sorted(GROUP_CHAT_TYPES))
    if excluded_types:
        placeholders = ", ".join("?" for _ in excluded_types)
        clauses.append(f"c.type NOT IN ({placeholders})")
        params.extend(excluded_types)

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
    include_bots: bool = False,
    include_groups: bool = False,
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
        include_bots=include_bots,
        include_groups=include_groups,
    )


def scoreboard(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    compare_previous: bool = False,
) -> pd.DataFrame:
    current = _scoreboard_row(conn, f)
    if not compare_previous or f.year_start is None or f.year_end is None:
        current["window"] = "current"
        return current

    span = f.year_end - f.year_start + 1
    prev_start = f.year_start - span
    prev_end = f.year_start - 1
    min_row = conn.execute("SELECT min(year)::INT FROM telegram.messages").fetchone()
    assert min_row is not None
    min_year = min_row[0]
    if prev_start < min_year:
        current["window"] = "current"
        current["compare_note"] = (
            f"previous window ({prev_start}–{prev_end}) predates data (min year {min_year})"
        )
        return current
    prev_f = FilterState(
        year_start=prev_start,
        year_end=prev_end,
        chat_types=list(f.chat_types),
        chat_ids=list(f.chat_ids),
        event_types=list(f.event_types),
        media_kinds=list(f.media_kinds),
        chat_name=f.chat_name,
        include_bots=f.include_bots,
        include_groups=f.include_groups,
    )
    prev = _scoreboard_row(conn, prev_f)
    current["window"] = "current"
    prev["window"] = f"previous ({prev_start}–{prev_end})"
    return pd.concat([current, prev], ignore_index=True)


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            count(*)::BIGINT AS events,
            count(*) FILTER (WHERE m.event_type = 'message')::BIGINT AS messages,
            count(DISTINCT m.chat_id)::BIGINT AS chats,
            count(*) FILTER (WHERE m.media_kind <> 'none')::BIGINT AS with_media,
            count(*) FILTER (WHERE m.reply_to_message_id IS NOT NULL)::BIGINT AS replies,
            round(
                100.0 * avg(
                    CASE WHEN m.reply_to_message_id IS NOT NULL THEN 1.0 ELSE 0.0 END
                ),
                1
            ) AS reply_pct,
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


def media_mix(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    exclude_none: bool = True,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    extra = " AND m.media_kind <> 'none'" if exclude_none else ""
    sql = f"""
        SELECT
            m.media_kind,
            count(*)::BIGINT AS events
        {_from_join()}
        WHERE {where}{extra}
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


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        WITH daily AS (
            SELECT m.ts_local::DATE AS day, count(*)::BIGINT AS events
            {_from_join()}
            WHERE {where}
            GROUP BY 1
        ),
        ranked AS (
            SELECT
                day,
                events,
                day - (row_number() OVER (ORDER BY day))::INT AS grp
            FROM daily
        ),
        streaks AS (
            SELECT grp, count(*) AS streak_days, sum(events) AS streak_events
            FROM ranked
            GROUP BY grp
        ),
        busiest AS (
            SELECT day, events
            FROM daily
            ORDER BY events DESC
            LIMIT 1
        )
        SELECT
            (SELECT max(streak_days) FROM streaks) AS longest_streak_days,
            (SELECT max(streak_events) FROM streaks) AS longest_streak_events,
            (SELECT day FROM busiest) AS busiest_day,
            (SELECT events FROM busiest) AS busiest_day_events
    """
    return _query_df(conn, sql, params)


def me_vs_them(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            m.year,
            count(*) FILTER (
                WHERE m.event_type = 'message' AND m.from_id = a.user_id
            )::BIGINT AS me,
            count(*) FILTER (
                WHERE m.event_type = 'message'
                  AND m.from_id IS DISTINCT FROM a.user_id
            )::BIGINT AS them
        {_from_join()}
        CROSS JOIN telegram.account a
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
    """
    return _query_df(conn, sql, params)


def monthly_by_chat_type(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            m.year,
            m.month,
            c.type AS chat_type,
            count(*)::BIGINT AS events
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """
    df = _query_df(conn, sql, params)
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            m.ts_local::DATE AS day,
            count(*)::BIGINT AS events
        {_from_join()}
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
    """
    return _query_df(conn, sql, params)


def bump_chart_chats(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    top_n: int = 8,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.append(top_n)
    sql = f"""
        WITH yearly AS (
            SELECT m.year, c.name AS chat_name, count(*)::BIGINT AS events
            {_from_join()}
            WHERE {where}
            GROUP BY 1, 2
        ),
        top_chats AS (
            SELECT chat_name
            FROM yearly
            GROUP BY 1
            ORDER BY sum(events) DESC
            LIMIT ?
        ),
        ranked AS (
            SELECT
                y.year,
                y.chat_name,
                y.events,
                row_number() OVER (PARTITION BY y.year ORDER BY y.events DESC) AS rank
            FROM yearly y
            INNER JOIN top_chats t ON y.chat_name = t.chat_name
        )
        SELECT year, chat_name, events, rank
        FROM ranked
        ORDER BY year, rank
    """
    return _query_df(conn, sql, params)


def chat_reply_scatter(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            c.chat_id,
            c.name AS chat_name,
            c.type AS chat_type,
            count(*)::BIGINT AS events,
            round(
                100.0 * avg(
                    CASE WHEN m.reply_to_message_id IS NOT NULL THEN 1.0 ELSE 0.0 END
                ),
                1
            ) AS reply_pct,
            max(m.ts_utc)::DATE AS last_day
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2, 3
        ORDER BY events DESC
    """
    return _query_df(conn, sql, params)


def forgotten_chats(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    min_events: int = 50,
    silent_years: int = 2,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.extend([min_events, silent_years, limit])
    sql = f"""
        WITH chat_span AS (
            SELECT
                c.chat_id,
                c.name AS chat_name,
                c.type AS chat_type,
                count(*)::BIGINT AS events,
                max(m.ts_utc) AS last_ts
            {_from_join()}
            WHERE {where}
            GROUP BY 1, 2, 3
            HAVING count(*) >= ?
        )
        SELECT
            chat_name,
            chat_type,
            events,
            last_ts::DATE AS last_day
        FROM chat_span
        WHERE last_ts < current_timestamp - (? * INTERVAL '1 year')
        ORDER BY events DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def comeback_chats(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    silent_years: int = 2,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.extend([silent_years, limit])
    sql = f"""
        WITH filtered AS (
            SELECT c.chat_id, c.name AS chat_name, m.ts_utc
            {_from_join()}
            WHERE {where}
        ),
        chat_span AS (
            SELECT
                chat_id,
                chat_name,
                min(ts_utc) AS first_in_window,
                max(ts_utc) AS last_in_window,
                count(*)::BIGINT AS window_events
            FROM filtered
            GROUP BY 1, 2
        ),
        prior AS (
            SELECT
                m.chat_id,
                max(m.ts_utc) AS last_before
            FROM telegram.messages m
            INNER JOIN chat_span a ON m.chat_id = a.chat_id
            WHERE m.ts_utc < a.first_in_window
            GROUP BY 1
        )
        SELECT
            a.chat_name,
            a.window_events,
            p.last_before::DATE AS last_before,
            a.first_in_window::DATE AS returned_on
        FROM chat_span a
        INNER JOIN prior p ON a.chat_id = p.chat_id
        WHERE p.last_before < a.first_in_window - (? * INTERVAL '1 year')
        ORDER BY a.window_events DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def reaction_mix(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 15,
) -> pd.DataFrame:
    where, params = _where_and_params(f)
    params.append(limit)
    sql = f"""
        SELECT
            r.emoji,
            sum(r.count)::BIGINT AS reactions
        FROM telegram.reactions r
        JOIN telegram.messages m
          ON m.chat_id = r.chat_id AND m.message_id = r.message_id
        JOIN telegram.chats c ON c.chat_id = m.chat_id
        WHERE {where}
        GROUP BY 1
        ORDER BY reactions DESC
        LIMIT ?
    """
    return _query_df(conn, sql, params)


def calls_by_year(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where_and_params(f)
    sql = f"""
        SELECT
            m.year,
            count(*)::BIGINT AS calls
        {_from_join()}
        WHERE {where} AND m.action ILIKE '%call%'
        GROUP BY 1
        ORDER BY 1
    """
    return _query_df(conn, sql, params)
