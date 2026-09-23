"""Ollama queries — filters, scoreboard, Wrapped analyses."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util

NARRATIVE_CONTEXT_KEYS = frozenset(
    {
        "filter_digest",
        "filters",
        "scoreboard",
        "streak",
        "model_mix",
        "tool_mix",
        "top_chats",
        "forgotten",
        "comebacks",
        "depth",
        "length_buckets",
        "attachments",
    }
)

# English function words. Constants only — never user text.
MESSAGE_STOPWORDS: tuple[str, ...] = (
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "your",
    "what",
    "how",
    "are",
    "can",
    "into",
    "about",
    "have",
    "will",
    "you",
    "not",
    "but",
    "was",
    "were",
    "been",
    "they",
    "them",
    "their",
    "its",
    "our",
    "out",
    "all",
    "any",
    "just",
    "like",
    "would",
    "could",
    "should",
    "there",
    "here",
    "when",
    "where",
    "which",
    "who",
    "why",
    "then",
    "than",
    "also",
    "more",
    "some",
    "such",
    "only",
    "other",
    "over",
    "after",
    "before",
    "because",
    "while",
    "each",
    "both",
    "very",
    "too",
    "has",
    "had",
    "did",
    "does",
    "don",
    "one",
    "get",
    "got",
)


def _stopword_sql() -> str:
    return ", ".join("'" + word.replace("'", "''") + "'" for word in MESSAGE_STOPWORDS)


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    models: list[str] = field(default_factory=list)
    title_search: str | None = None
    chat_id: str | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        chip = query_util.year_chip(self.year_start, self.year_end)
        if chip is not None:
            chips.append(chip)
        for model in self.models:
            chips.append(("model", f"model={model}"))
        if self.title_search:
            chips.append(("title_search", f"title: {self.title_search}"))
        if self.chat_id:
            chips.append(("chat_id", f"chat: {self.chat_id[:8]}…"))
        return chips

    def filter_digest(self) -> str:
        payload = {
            "year_start": self.year_start,
            "year_end": self.year_end,
            "models": sorted(self.models),
            "title_search": self.title_search,
            "chat_id": self.chat_id,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def has_table(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return query_util.has_table(conn, "ollama", table)


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def _chat_match(f: FilterState, alias: str = "c") -> tuple[str, list[Any]]:
    """Chat identity filters. Year stays on the row being counted."""
    p = f"{alias}."
    clauses: list[str] = []
    params: list[Any] = []
    if f.chat_id:
        clauses.append(f"{p}chat_id = ?")
        params.append(f.chat_id)
    if f.title_search:
        clauses.append(f"contains(lower(coalesce({p}title, '')), lower(?))")
        params.append(f.title_search)
    if f.models:
        placeholders = ", ".join("?" for _ in f.models)
        clauses.append(
            f"exists (SELECT 1 FROM ollama.messages mm "
            f"WHERE mm.chat_id = {p}chat_id AND mm.model_name IN ({placeholders}))"
        )
        params.extend(f.models)
    return (" AND ".join(clauses) if clauses else "1=1"), params


def _chat_where(f: FilterState, alias: str = "c") -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    query_util.append_year_clause(clauses, params, alias, f.year_start, f.year_end)
    match, match_params = _chat_match(f, alias)
    if match != "1=1":
        clauses.append(match)
        params.extend(match_params)
    return (" AND ".join(clauses) if clauses else "1=1"), params


def _msg_where(f: FilterState, alias: str = "m") -> tuple[str, list[Any]]:
    p = f"{alias}."
    clauses: list[str] = [f"{p}created_at_local IS NOT NULL"]
    params: list[Any] = []
    query_util.append_year_clause(clauses, params, alias, f.year_start, f.year_end)
    if f.chat_id:
        clauses.append(f"{p}chat_id = ?")
        params.append(f.chat_id)
    match, match_params = _chat_match(
        FilterState(
            models=list(f.models),
            title_search=f.title_search,
        ),
        "c",
    )
    if match != "1=1":
        clauses.append(
            f"exists (SELECT 1 FROM ollama.chats c "
            f"WHERE c.chat_id = {p}chat_id AND {match})"
        )
        params.extend(match_params)
    return " AND ".join(clauses), params


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int | None,
    year_end: int | None,
    models: list[str] | None = None,
    title_search: str = "",
    chat_id: str | None = None,
) -> FilterState:
    ys = year_start if year_start is not None else bounds.get("min_year")
    ye = year_end if year_end is not None else bounds.get("max_year")
    return FilterState(
        year_start=ys,
        year_end=ye,
        models=list(models or []),
        title_search=(title_search or "").strip() or None,
        chat_id=chat_id or None,
    )


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT, max(year)::INT,
            min(created_at_local)::DATE,
            max(created_at_local)::DATE
        FROM ollama.messages
        WHERE created_at_local IS NOT NULL
        """).fetchone()
    assert row is not None
    min_year, max_year, first_day, last_day = row
    if min_year is None or max_year is None:
        chat_row = conn.execute("""
            SELECT min(year)::INT, max(year)::INT,
                   min(created_at_local)::DATE, max(created_at_local)::DATE
            FROM ollama.chats
            WHERE created_at_local IS NOT NULL
            """).fetchone()
        assert chat_row is not None
        min_year, max_year, first_day, last_day = chat_row
    if min_year is None or max_year is None:
        min_year, max_year = 2025, 2025
    models = [r[0] for r in conn.execute("""
            SELECT model_name FROM ollama.messages
            WHERE model_name IS NOT NULL
            GROUP BY 1 ORDER BY count(*) DESC
            """).fetchall() if r[0]]
    return {
        "min_year": int(min_year),
        "max_year": int(max_year),
        "first_day": first_day,
        "last_day": last_day,
        "models": models,
    }


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
    min_row = conn.execute(
        "SELECT min(year)::INT FROM ollama.messages WHERE year IS NOT NULL"
    ).fetchone()
    min_year = min_row[0] if min_row else None
    if min_year is None or prev_start < min_year:
        current["window"] = "current"
        current["compare_note"] = (
            f"previous window ({prev_start}–{prev_end}) predates data "
            f"(min year {min_year})"
        )
        return current
    prev_f = FilterState(
        year_start=prev_start,
        year_end=prev_end,
        models=list(f.models),
        title_search=f.title_search,
        chat_id=f.chat_id,
    )
    prev = _scoreboard_row(conn, prev_f)
    current["window"] = "current"
    prev["window"] = f"previous ({prev_start}–{prev_end})"
    return pd.concat([current, prev], ignore_index=True)


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    cw, cp = _chat_where(f)
    mw, mp = _msg_where(f)
    frame = _query_df(
        conn,
        f"""
        SELECT
            (SELECT count(*)::BIGINT FROM ollama.chats c WHERE {cw}) AS chats,
            (SELECT count(*)::BIGINT FROM ollama.messages m WHERE {mw}) AS messages,
            (SELECT count(*)::BIGINT FROM ollama.messages m
             WHERE {mw} AND m.role = 'user') AS user_messages,
            (SELECT count(*)::BIGINT FROM ollama.messages m
             WHERE {mw} AND m.role = 'assistant') AS assistant_messages,
            (SELECT coalesce(sum(m.char_count), 0)::BIGINT FROM ollama.messages m
             WHERE {mw} AND m.role = 'user') AS user_chars,
            (SELECT coalesce(sum(m.char_count), 0)::BIGINT FROM ollama.messages m
             WHERE {mw} AND m.role = 'assistant') AS assistant_chars,
            (SELECT count(DISTINCT m.created_at_local::DATE)::BIGINT
             FROM ollama.messages m WHERE {mw}) AS active_days,
            (SELECT count(DISTINCT m.model_name)::BIGINT FROM ollama.messages m
             WHERE {mw} AND m.model_name IS NOT NULL) AS models,
            (SELECT count(*)::BIGINT FROM ollama.messages m
             WHERE {mw} AND m.thinking_chars > 0) AS thinking_messages,
            (SELECT coalesce(sum(m.thinking_chars), 0)::BIGINT FROM ollama.messages m
             WHERE {mw}) AS thinking_chars,
            (SELECT count(*)::BIGINT FROM ollama.attachments a
             WHERE exists (
               SELECT 1 FROM ollama.messages m
               WHERE m.message_id = a.message_id AND {mw}
             )) AS attachments,
            (SELECT count(*)::BIGINT FROM ollama.tool_calls t
             WHERE exists (
               SELECT 1 FROM ollama.messages m
               WHERE m.message_id = t.message_id AND {mw}
             )) AS tool_calls,
            (SELECT min(m.created_at_local)::DATE FROM ollama.messages m
             WHERE {mw}) AS first_day,
            (SELECT max(m.created_at_local)::DATE FROM ollama.messages m
             WHERE {mw}) AS last_day
        """,
        [
            *cp,
            *mp,
            *mp,
            *mp,
            *mp,
            *mp,
            *mp,
            *mp,
            *mp,
            *mp,
            *mp,
            *mp,
            *mp,
            *mp,
        ],
    )
    latency = reply_latency(conn, f)
    median = None
    if not latency.empty:
        value = latency.iloc[0]["median_minutes"]
        if value is not None and pd.notna(value):
            median = float(value)
    frame["median_reply_minutes"] = median
    return frame


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH daily AS (
            SELECT m.created_at_local::DATE AS day, count(*)::BIGINT AS messages
            FROM ollama.messages m
            WHERE {where}
            GROUP BY 1
        ),
        ranked AS (
            SELECT
                day,
                messages,
                day - (row_number() OVER (ORDER BY day))::INT AS grp
            FROM daily
        ),
        streaks AS (
            SELECT grp, count(*) AS streak_days, sum(messages) AS streak_messages
            FROM ranked
            GROUP BY grp
        ),
        busiest AS (
            SELECT day, messages FROM daily ORDER BY messages DESC LIMIT 1
        )
        SELECT
            (SELECT max(streak_days) FROM streaks) AS longest_streak_days,
            (SELECT max(streak_messages) FROM streaks) AS longest_streak_messages,
            (SELECT day FROM busiest) AS busiest_day,
            (SELECT messages FROM busiest) AS busiest_day_messages,
            (SELECT count(*) FROM daily) AS active_days
        """,
        params,
    )


def messages_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year::INT, month::INT) AS year_month,
            count(*)::BIGINT AS messages,
            count(*) FILTER (WHERE role = 'user')::BIGINT AS user_messages,
            count(*) FILTER (WHERE role = 'assistant')::BIGINT AS assistant_messages,
            count(DISTINCT chat_id)::BIGINT AS chats,
            coalesce(sum(char_count) FILTER (WHERE role = 'user'), 0)::BIGINT
                AS user_chars
        FROM ollama.messages m
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def messages_daily_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT m.created_at_local::DATE AS day, count(*)::BIGINT AS messages
        FROM ollama.messages m
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def messages_monthly_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    monthly = messages_monthly(conn, f)
    if monthly.empty:
        return monthly
    return monthly[["year_month", "messages"]]


def chats_monthly_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _chat_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year::INT, month::INT) AS year_month,
            count(*)::BIGINT AS chats
        FROM ollama.chats c
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def chats_daily_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _chat_where(f)
    return _query_df(
        conn,
        f"""
        SELECT c.created_at_local::DATE AS day, count(*)::BIGINT AS chats
        FROM ollama.chats c
        WHERE {where} AND c.created_at_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def chat_messages_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    chat_id: str,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end, chat_id=chat_id)
    monthly = messages_monthly(conn, f)
    if monthly.empty:
        return monthly
    return monthly[["year_month", "messages"]]


def chat_options(conn: duckdb.DuckDBPyConnection) -> list[dict[str, str]]:
    rows = conn.execute("""
        SELECT chat_id, coalesce(nullif(title, ''), chat_id) AS title
        FROM ollama.chats
        ORDER BY created_at_local DESC NULLS LAST
        LIMIT 200
        """).fetchall()
    return [{"value": r[0], "label": f"{r[1][:60]} ({r[0][:8]})"} for r in rows]


def model_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(model_name, '(none)') AS model_name,
            coalesce(model_family, '(none)') AS model_family,
            count(*)::BIGINT AS messages,
            count(DISTINCT chat_id)::BIGINT AS chats
        FROM ollama.messages m
        WHERE {where} AND role = 'assistant'
        GROUP BY 1, 2
        ORDER BY 3 DESC
        """,
        params,
    )


def model_stack(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year::INT, month::INT) AS year_month,
            coalesce(model_family, 'unknown') AS model_family,
            count(*)::BIGINT AS messages
        FROM ollama.messages m
        WHERE {where} AND role = 'assistant'
          AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 3 DESC
        """,
        params,
    )


def model_rank_bump(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, top_n: int = 8
) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH yearly AS (
            SELECT
                year,
                coalesce(model_family, 'unknown') AS model_family,
                count(*)::BIGINT AS messages
            FROM ollama.messages m
            WHERE {where} AND role = 'assistant' AND year IS NOT NULL
            GROUP BY 1, 2
        ),
        ranked AS (
            SELECT
                year,
                model_family,
                messages,
                row_number() OVER (PARTITION BY year ORDER BY messages DESC) AS rank
            FROM yearly
        ),
        keep AS (
            SELECT model_family
            FROM ranked
            WHERE rank <= ?
            GROUP BY 1
        )
        SELECT r.year, r.model_family, r.messages, r.rank
        FROM ranked r
        JOIN keep k ON k.model_family = r.model_family
        ORDER BY r.year, r.rank
        """,
        [*params, top_n],
    )


def thinking_by_model(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(model_name, '(none)') AS model_name,
            count(*) FILTER (WHERE thinking_chars > 0)::BIGINT AS thinking_messages,
            coalesce(sum(thinking_chars), 0)::BIGINT AS thinking_chars,
            round(avg(thinking_seconds), 1) AS avg_thinking_seconds
        FROM ollama.messages m
        WHERE {where} AND role = 'assistant'
        GROUP BY 1
        HAVING count(*) FILTER (WHERE thinking_chars > 0) > 0
        ORDER BY thinking_chars DESC
        """,
        params,
    )


def tool_name_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    mw, mp = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT coalesce(nullif(t.tool_name, ''), '(unknown)') AS tool_name,
               count(*)::BIGINT AS tool_calls
        FROM ollama.tool_calls t
        WHERE exists (
            SELECT 1 FROM ollama.messages m
            WHERE m.message_id = t.message_id AND {mw}
        )
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 25
        """,
        mp,
    )


def weekday_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT weekday::INT AS dow, hour::INT AS hour, count(*)::BIGINT AS messages
        FROM ollama.messages m
        WHERE {where} AND weekday IS NOT NULL AND hour IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            m.created_at_local::DATE AS day,
            isodow(m.created_at_local) AS weekday,
            weekofyear(m.created_at_local) AS iso_week,
            year(m.created_at_local) AS year,
            count(*)::BIGINT AS events,
            count(DISTINCT m.chat_id)::BIGINT AS chats
        FROM ollama.messages m
        WHERE {where}
        GROUP BY 1, 2, 3, 4
        ORDER BY 1
        """,
        params,
    )


def top_chats(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 40
) -> pd.DataFrame:
    cw, cp = _chat_where(f)
    return _query_df(
        conn,
        f"""
        WITH stats AS (
            SELECT
                m.chat_id,
                count(*)::BIGINT AS message_count,
                coalesce(sum(m.char_count), 0)::BIGINT AS char_count,
                count(*) FILTER (WHERE m.thinking_chars > 0)::BIGINT AS thinking_messages,
                max(m.model_name) FILTER (WHERE m.role = 'assistant') AS model_name,
                min(m.created_at_local) AS first_local,
                max(m.created_at_local) AS last_local
            FROM ollama.messages m
            GROUP BY 1
        )
        SELECT
            c.chat_id,
            c.title,
            c.created_at_local,
            coalesce(s.message_count, 0) AS message_count,
            coalesce(s.char_count, 0) AS char_count,
            coalesce(s.thinking_messages, 0) AS thinking_messages,
            s.model_name,
            s.last_local
        FROM ollama.chats c
        LEFT JOIN stats s ON s.chat_id = c.chat_id
        WHERE {cw}
        ORDER BY coalesce(s.message_count, 0) DESC, c.created_at_local DESC NULLS LAST
        LIMIT ?
        """,
        [*cp, limit],
    )


def chat_scatter(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    cw, cp = _chat_where(f)
    return _query_df(
        conn,
        f"""
        WITH stats AS (
            SELECT
                chat_id,
                count(*)::BIGINT AS n_messages,
                coalesce(sum(char_count), 0)::BIGINT AS n_chars,
                min(created_at_local)::DATE AS first_day,
                max(created_at_local)::DATE AS last_day,
                max(model_family) FILTER (WHERE role = 'assistant') AS model_family
            FROM ollama.messages
            GROUP BY 1
        )
        SELECT
            c.chat_id,
            c.title,
            coalesce(s.n_messages, 0) AS n_messages,
            coalesce(s.n_chars, 0) AS n_chars,
            coalesce(s.model_family, '(none)') AS model_family,
            coalesce(date_diff('day', s.first_day, s.last_day), 0) AS span_days
        FROM ollama.chats c
        JOIN stats s ON s.chat_id = c.chat_id
        WHERE {cw} AND s.n_messages > 0
        ORDER BY s.n_messages DESC
        LIMIT 500
        """,
        cp,
    )


def forgotten_chats(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, silent_days: int = 90
) -> pd.DataFrame:
    cw, cp = _chat_where(f)
    return _query_df(
        conn,
        f"""
        WITH last_msg AS (
            SELECT chat_id, max(created_at_local)::DATE AS last_day,
                   count(*)::BIGINT AS message_count
            FROM ollama.messages
            WHERE created_at_local IS NOT NULL
            GROUP BY 1
        ),
        latest AS (
            SELECT max(last_day) AS max_day FROM last_msg
        )
        SELECT
            c.chat_id,
            c.title,
            l.message_count,
            l.last_day,
            date_diff('day', l.last_day, (SELECT max_day FROM latest)) AS days_silent
        FROM ollama.chats c
        JOIN last_msg l ON l.chat_id = c.chat_id
        WHERE {cw}
          AND date_diff('day', l.last_day, (SELECT max_day FROM latest)) >= ?
        ORDER BY days_silent DESC
        LIMIT 40
        """,
        [*cp, silent_days],
    )


def comeback_chats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Chats with a ≥30-day gap between first and last message."""
    mw, mp = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH bounds AS (
            SELECT
                m.chat_id,
                min(m.created_at_local)::DATE AS first_day,
                max(m.created_at_local)::DATE AS last_day,
                count(*)::BIGINT AS n_messages
            FROM ollama.messages m
            WHERE {mw}
            GROUP BY 1
        )
        SELECT
            b.chat_id,
            c.title,
            b.first_day,
            b.last_day,
            date_diff('day', b.first_day, b.last_day) AS span_days,
            b.n_messages
        FROM bounds b
        JOIN ollama.chats c ON c.chat_id = b.chat_id
        WHERE date_diff('day', b.first_day, b.last_day) >= 30
        ORDER BY span_days DESC
        LIMIT 40
        """,
        mp,
    )


def role_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT role, count(*)::BIGINT AS messages
        FROM ollama.messages m
        WHERE {where}
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        params,
    )


def message_length_buckets(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH tagged AS (
            SELECT
                CASE
                    WHEN coalesce(char_count, 0) < 40 THEN 1
                    WHEN char_count < 200 THEN 2
                    WHEN char_count < 1000 THEN 3
                    ELSE 4
                END AS ord,
                CASE
                    WHEN coalesce(char_count, 0) < 40 THEN '<40'
                    WHEN char_count < 200 THEN '40–199'
                    WHEN char_count < 1000 THEN '200–999'
                    ELSE '1000+'
                END AS bucket
            FROM ollama.messages m
            WHERE {where} AND role = 'user'
        )
        SELECT bucket, count(*)::BIGINT AS messages
        FROM tagged
        GROUP BY bucket, ord
        ORDER BY ord
        """,
        params,
    )


def chat_depth(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    cw, cp = _chat_where(f)
    return _query_df(
        conn,
        f"""
        WITH counts AS (
            SELECT c.chat_id, count(m.message_id)::BIGINT AS message_count
            FROM ollama.chats c
            LEFT JOIN ollama.messages m ON m.chat_id = c.chat_id
            WHERE {cw}
            GROUP BY 1
        ),
        tagged AS (
            SELECT
                CASE
                    WHEN message_count <= 2 THEN 1
                    WHEN message_count <= 10 THEN 2
                    WHEN message_count <= 40 THEN 3
                    ELSE 4
                END AS ord,
                CASE
                    WHEN message_count <= 2 THEN '1–2'
                    WHEN message_count <= 10 THEN '3–10'
                    WHEN message_count <= 40 THEN '11–40'
                    ELSE '41+'
                END AS bucket
            FROM counts
        )
        SELECT bucket, count(*)::BIGINT AS chats
        FROM tagged
        GROUP BY bucket, ord
        ORDER BY ord
        """,
        cp,
    )


def reply_latency(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """User → next assistant latency (minutes) within a chat."""
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH ordered AS (
            SELECT
                chat_id,
                role,
                created_at_local,
                lead(role) OVER (
                    PARTITION BY chat_id ORDER BY ordinal, created_at_local
                ) AS next_role,
                lead(created_at_local) OVER (
                    PARTITION BY chat_id ORDER BY ordinal, created_at_local
                ) AS next_ts
            FROM ollama.messages m
            WHERE {where}
              AND role IN ('user', 'assistant')
              AND created_at_local IS NOT NULL
        )
        SELECT
            count(*)::BIGINT AS pairs,
            round(avg(epoch(next_ts - created_at_local) / 60.0), 2) AS mean_minutes,
            round(median(epoch(next_ts - created_at_local) / 60.0), 2) AS median_minutes,
            round(quantile_cont(epoch(next_ts - created_at_local) / 60.0, 0.9), 2)
                AS p90_minutes
        FROM ordered
        WHERE role = 'user' AND next_role = 'assistant' AND next_ts IS NOT NULL
          AND epoch(next_ts - created_at_local) BETWEEN 0 AND 86400 * 2
        """,
        params,
    )


def attachment_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    mw, mp = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(nullif(a.extension, ''), '(none)') AS extension,
            count(*)::BIGINT AS attachments,
            coalesce(sum(a.byte_size), 0)::BIGINT AS bytes
        FROM ollama.attachments a
        WHERE exists (
            SELECT 1 FROM ollama.messages m
            WHERE m.message_id = a.message_id AND {mw}
        )
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        mp,
    )


def attachments_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    mw, mp = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', m.year::INT, m.month::INT) AS year_month,
            count(*)::BIGINT AS attachments,
            coalesce(sum(a.byte_size), 0)::BIGINT AS bytes
        FROM ollama.attachments a
        JOIN ollama.messages m ON m.message_id = a.message_id
        WHERE {mw} AND m.year IS NOT NULL AND m.month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        mp,
    )


def chat_messages(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 400
) -> pd.DataFrame:
    if not f.chat_id:
        return pd.DataFrame()
    return _query_df(
        conn,
        """
        SELECT
            m.ordinal,
            m.role,
            m.created_at_local,
            m.model_name,
            m.char_count,
            m.thinking_chars,
            left(coalesce(m.text, ''), 2000) AS text_preview,
            left(coalesce(m.thinking, ''), 500) AS thinking_preview,
            (
                SELECT string_agg(a.filename, ', ' ORDER BY a.attachment_id)
                FROM ollama.attachments a
                WHERE a.message_id = m.message_id
            ) AS attachments
        FROM ollama.messages m
        WHERE m.chat_id = ?
        ORDER BY m.ordinal
        LIMIT ?
        """,
        [f.chat_id, limit],
    )


def message_tokens(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    role: str | None = None,
    limit: int = 120,
) -> pd.DataFrame:
    where, params = _msg_where(f)
    stops = _stopword_sql()
    role_sql = ""
    if role in {"user", "assistant"}:
        role_sql = " AND m.role = ?"
        params.append(role)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        WITH raw AS (
            SELECT lower(
                unnest(regexp_extract_all(coalesce(m.text, ''), '[A-Za-z]{{3,}}'))
            ) AS term
            FROM ollama.messages m
            WHERE {where}{role_sql}
              AND m.role IN ('user', 'assistant')
        )
        SELECT term, count(*)::BIGINT AS n
        FROM raw
        WHERE term NOT IN ({stops})
        GROUP BY 1
        ORDER BY n DESC, term
        LIMIT ?
        """,
        params,
    )


def user_bigrams(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 80
) -> pd.DataFrame:
    where, params = _msg_where(f)
    stops = _stopword_sql()
    params.append(limit)
    return _query_df(
        conn,
        f"""
        WITH scoped AS (
            SELECT m.message_id, coalesce(m.text, '') AS text
            FROM ollama.messages m
            WHERE {where} AND m.role = 'user'
        ),
        toks AS (
            SELECT
                s.message_id,
                lower(u.term) AS term,
                u.pos
            FROM scoped s,
            LATERAL unnest(
                regexp_extract_all(s.text, '[A-Za-z]{{3,}}')
            ) WITH ORDINALITY AS u(term, pos)
        ),
        filtered AS (
            SELECT message_id, term, pos
            FROM toks
            WHERE term NOT IN ({stops})
        ),
        pairs AS (
            SELECT
                term || ' ' || lead(term) OVER (
                    PARTITION BY message_id ORDER BY pos
                ) AS term
            FROM filtered
        )
        SELECT term, count(*)::BIGINT AS n
        FROM pairs
        WHERE term IS NOT NULL
        GROUP BY 1
        ORDER BY n DESC, term
        LIMIT ?
        """,
        params,
    )


def narrative_context(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> dict[str, Any]:
    return {
        "filter_digest": f.filter_digest(),
        "filters": {
            "year_start": f.year_start,
            "year_end": f.year_end,
            "models": list(f.models),
            "title_search": f.title_search,
            "chat_id": f.chat_id,
        },
        "scoreboard": scoreboard(conn, f).to_dict(orient="records"),
        "streak": streak_stats(conn, f).to_dict(orient="records"),
        "model_mix": model_mix(conn, f).head(8).to_dict(orient="records"),
        "tool_mix": tool_name_mix(conn, f).head(8).to_dict(orient="records"),
        "top_chats": top_chats(conn, f, limit=8)[
            ["chat_id", "title", "message_count", "char_count", "model_name"]
        ].to_dict(orient="records"),
        "forgotten": forgotten_chats(conn, f).head(5).to_dict(orient="records"),
        "comebacks": comeback_chats(conn, f).head(5).to_dict(orient="records"),
        "depth": chat_depth(conn, f).to_dict(orient="records"),
        "length_buckets": message_length_buckets(conn, f).to_dict(orient="records"),
        "attachments": attachment_mix(conn, f).head(8).to_dict(orient="records"),
    }
