"""Cursor History queries — filters, scoreboard, Wrapped-lite analyses."""

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
        "source_mix",
        "tool_mix",
        "top_sessions",
        "forgotten",
        "comebacks",
        "depth",
        "length_buckets",
        "mode_mix",
    }
)


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    source_kinds: list[str] = field(default_factory=list)
    project_slugs: list[str] = field(default_factory=list)
    title_search: str | None = None
    text_search: str | None = None
    session_id: str | None = None
    subagents_only: bool = False
    hide_subagents: bool = False

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        chip = query_util.year_chip(self.year_start, self.year_end)
        if chip is not None:
            chips.append(chip)
        for kind in self.source_kinds:
            chips.append(("source_kind", f"source={kind}"))
        for slug in self.project_slugs:
            chips.append(("project_slug", f"project={slug}"))
        if self.title_search:
            chips.append(("title_search", f"title: {self.title_search}"))
        if self.text_search:
            chips.append(("text_search", f"text: {self.text_search}"))
        if self.session_id:
            chips.append(("session_id", f"session: {self.session_id[:8]}…"))
        if self.subagents_only:
            chips.append(("subagents_only", "subagents only"))
        if self.hide_subagents:
            chips.append(("hide_subagents", "hide subagents"))
        return chips

    def filter_digest(self) -> str:
        payload = {
            "year_start": self.year_start,
            "year_end": self.year_end,
            "source_kinds": sorted(self.source_kinds),
            "project_slugs": sorted(self.project_slugs),
            "title_search": self.title_search,
            "text_search": self.text_search,
            "session_id": self.session_id,
            "subagents_only": self.subagents_only,
            "hide_subagents": self.hide_subagents,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def has_table(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return query_util.has_table(conn, "cursor_history", table)


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def _session_where(f: FilterState, alias: str = "s") -> tuple[str, list[Any]]:
    p = f"{alias}."
    clauses: list[str] = []
    params: list[Any] = []
    query_util.append_year_clause(clauses, params, alias, f.year_start, f.year_end)
    if f.session_id:
        clauses.append(f"{p}session_id = ?")
        params.append(f.session_id)
    if f.source_kinds:
        placeholders = ", ".join("?" for _ in f.source_kinds)
        clauses.append(f"{p}source_kind IN ({placeholders})")
        params.extend(f.source_kinds)
    if f.project_slugs:
        placeholders = ", ".join("?" for _ in f.project_slugs)
        clauses.append(f"{p}project_slug IN ({placeholders})")
        params.extend(f.project_slugs)
    if f.title_search:
        clauses.append(f"contains(lower(coalesce({p}title, '')), lower(?))")
        params.append(f.title_search)
    if f.subagents_only:
        clauses.append(f"{p}is_subagent")
    if f.hide_subagents:
        clauses.append(f"NOT coalesce({p}is_subagent, false)")
    return (" AND ".join(clauses) if clauses else "1=1"), params


def _msg_where(f: FilterState, alias: str = "m") -> tuple[str, list[Any]]:
    p = f"{alias}."
    clauses: list[str] = [f"{p}created_at_local IS NOT NULL"]
    params: list[Any] = []
    query_util.append_year_clause(clauses, params, alias, f.year_start, f.year_end)
    if f.session_id:
        clauses.append(f"{p}session_id = ?")
        params.append(f.session_id)
    if f.text_search:
        clauses.append(f"contains(lower(coalesce({p}text, '')), lower(?))")
        params.append(f.text_search)
    if (
        f.source_kinds
        or f.project_slugs
        or f.title_search
        or f.subagents_only
        or f.hide_subagents
    ):
        sw, sp = _session_where(f, "s")
        clauses.append(
            f"exists (SELECT 1 FROM cursor_history.sessions s "
            f"WHERE s.session_id = {p}session_id AND {sw})"
        )
        params.extend(sp)
    return " AND ".join(clauses), params


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int | None,
    year_end: int | None,
    source_kinds: list[str] | None = None,
    project_slugs: list[str] | None = None,
    title_search: str = "",
    text_search: str = "",
    session_id: str | None = None,
    subagents_only: bool = False,
    hide_subagents: bool = False,
) -> FilterState:
    ys = year_start if year_start is not None else bounds.get("min_year")
    ye = year_end if year_end is not None else bounds.get("max_year")
    return FilterState(
        year_start=ys,
        year_end=ye,
        source_kinds=list(source_kinds or []),
        project_slugs=list(project_slugs or []),
        title_search=(title_search or "").strip() or None,
        text_search=(text_search or "").strip() or None,
        session_id=session_id or None,
        subagents_only=bool(subagents_only),
        hide_subagents=bool(hide_subagents),
    )


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT, max(year)::INT,
            min(created_at_local)::DATE,
            max(coalesce(updated_at_local, created_at_local))::DATE
        FROM cursor_history.sessions
        WHERE created_at_local IS NOT NULL OR updated_at_local IS NOT NULL
        """).fetchone()
    assert row is not None
    min_year, max_year, first_day, last_day = row
    if min_year is None or max_year is None:
        min_year, max_year = 2025, 2025
    source_kinds = [r[0] for r in conn.execute("""
            SELECT source_kind FROM cursor_history.sessions
            WHERE source_kind IS NOT NULL
            GROUP BY 1 ORDER BY count(*) DESC
            """).fetchall() if r[0]]
    project_slugs = [r[0] for r in conn.execute("""
            SELECT project_slug FROM cursor_history.sessions
            WHERE project_slug IS NOT NULL
            GROUP BY 1 ORDER BY count(*) DESC
            LIMIT 40
            """).fetchall() if r[0]]
    return {
        "min_year": int(min_year),
        "max_year": int(max_year),
        "first_day": first_day,
        "last_day": last_day,
        "source_kinds": source_kinds,
        "project_slugs": project_slugs,
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
        "SELECT min(year)::INT FROM cursor_history.sessions WHERE year IS NOT NULL"
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
        source_kinds=list(f.source_kinds),
        project_slugs=list(f.project_slugs),
        title_search=f.title_search,
        text_search=f.text_search,
        session_id=f.session_id,
        subagents_only=f.subagents_only,
        hide_subagents=f.hide_subagents,
    )
    prev = _scoreboard_row(conn, prev_f)
    current["window"] = "current"
    prev["window"] = f"previous ({prev_start}–{prev_end})"
    return pd.concat([current, prev], ignore_index=True)


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    sw, sp = _session_where(f)
    mw, mp = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            (SELECT count(*)::BIGINT FROM cursor_history.sessions s WHERE {sw}) AS sessions,
            (SELECT count(*)::BIGINT FROM cursor_history.messages m WHERE {mw}) AS messages,
            (SELECT count(*)::BIGINT FROM cursor_history.tool_calls t
             WHERE exists (
               SELECT 1 FROM cursor_history.sessions s
               WHERE s.session_id = t.session_id AND {sw}
             )) AS tool_calls,
            (SELECT count(DISTINCT m.created_at_local::DATE)::BIGINT
             FROM cursor_history.messages m WHERE {mw}) AS active_days,
            (SELECT count(*)::BIGINT FROM cursor_history.messages m
             WHERE {mw} AND m.role = 'user') AS user_messages,
            (SELECT count(*)::BIGINT FROM cursor_history.messages m
             WHERE {mw} AND m.role = 'assistant') AS assistant_messages,
            (SELECT coalesce(sum(m.char_count), 0)::BIGINT FROM cursor_history.messages m
             WHERE {mw} AND m.role = 'user') AS user_chars,
            (SELECT count(*)::BIGINT FROM cursor_history.messages m
             WHERE {mw} AND m.has_thinking) AS thinking_messages,
            (SELECT count(*)::BIGINT FROM cursor_history.messages m
             WHERE {mw} AND m.has_diff) AS diff_messages,
            (SELECT round(
                avg(s.message_count)::DOUBLE, 1
             ) FROM cursor_history.sessions s WHERE {sw}) AS avg_session_depth,
            (SELECT round(
                avg(CASE WHEN s.message_count > 0
                    THEN s.tool_call_count::DOUBLE / s.message_count END), 2
             ) FROM cursor_history.sessions s WHERE {sw}) AS avg_tools_per_message,
            (SELECT count(*)::BIGINT FROM cursor_history.sessions s
             WHERE {sw} AND s.is_subagent) AS subagent_sessions,
            (SELECT min(m.created_at_local)::DATE FROM cursor_history.messages m
             WHERE {mw}) AS first_day,
            (SELECT max(m.created_at_local)::DATE FROM cursor_history.messages m
             WHERE {mw}) AS last_day
        """,
        [*sp, *mp, *sp, *mp, *mp, *mp, *mp, *mp, *mp, *sp, *sp, *sp, *mp, *mp],
    )


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH daily AS (
            SELECT m.created_at_local::DATE AS day, count(*)::BIGINT AS messages
            FROM cursor_history.messages m
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
            count(DISTINCT session_id)::BIGINT AS sessions,
            coalesce(sum(char_count) FILTER (WHERE role = 'user'), 0)::BIGINT AS user_chars
        FROM cursor_history.messages m
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
        FROM cursor_history.messages m
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
    return messages_monthly(conn, f)[["year_month", "messages"]]


def sessions_monthly_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _session_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year::INT, month::INT) AS year_month,
            count(*)::BIGINT AS sessions
        FROM cursor_history.sessions s
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def sessions_daily_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _session_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(s.created_at_local, s.updated_at_local)::DATE AS day,
            count(*)::BIGINT AS sessions
        FROM cursor_history.sessions s
        WHERE {where}
          AND coalesce(s.created_at_local, s.updated_at_local) IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def session_messages_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    session_id: str,
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end, session_id=session_id)
    return messages_monthly(conn, f)[["year_month", "messages"]]


def session_options(conn: duckdb.DuckDBPyConnection) -> list[dict[str, str]]:
    rows = conn.execute("""
        SELECT session_id, coalesce(title, session_id) AS title
        FROM cursor_history.sessions
        ORDER BY coalesce(updated_at_local, created_at_local) DESC NULLS LAST
        LIMIT 200
        """).fetchall()
    return [{"value": r[0], "label": f"{r[1][:60]} ({r[0][:8]})"} for r in rows]


def source_kind_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _session_where(f)
    return _query_df(
        conn,
        f"""
        SELECT source_kind, count(*)::BIGINT AS sessions
        FROM cursor_history.sessions s
        WHERE {where}
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        params,
    )


def tool_name_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    sw, sp = _session_where(f)
    return _query_df(
        conn,
        f"""
        SELECT coalesce(t.tool_name, '(unknown)') AS tool_name,
               count(*)::BIGINT AS tool_calls
        FROM cursor_history.tool_calls t
        WHERE exists (
            SELECT 1 FROM cursor_history.sessions s
            WHERE s.session_id = t.session_id AND {sw}
        )
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 25
        """,
        sp,
    )


def weekday_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT weekday::INT AS dow, hour::INT AS hour, count(*)::BIGINT AS messages
        FROM cursor_history.messages m
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
            count(DISTINCT m.session_id)::BIGINT AS sessions
        FROM cursor_history.messages m
        WHERE {where}
        GROUP BY 1, 2, 3, 4
        ORDER BY 1
        """,
        params,
    )


def top_sessions(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 40
) -> pd.DataFrame:
    sw, sp = _session_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            s.session_id,
            s.title,
            s.source_kind,
            s.project_slug,
            s.is_subagent,
            s.subagent_type,
            s.message_count,
            s.tool_call_count,
            s.unified_mode,
            s.created_at_local,
            s.updated_at_local
        FROM cursor_history.sessions s
        WHERE {sw}
        ORDER BY s.message_count DESC NULLS LAST,
                 coalesce(s.updated_at_local, s.created_at_local) DESC NULLS LAST
        LIMIT ?
        """,
        [*sp, limit],
    )


def session_scatter(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    sw, sp = _session_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            s.session_id,
            s.title,
            s.source_kind,
            s.message_count AS n_messages,
            s.tool_call_count AS n_tools,
            coalesce(
                date_diff('day', s.created_at_local::DATE,
                          coalesce(s.updated_at_local, s.created_at_local)::DATE),
                0
            ) AS span_days,
            s.is_subagent
        FROM cursor_history.sessions s
        WHERE {sw} AND s.message_count > 0
        ORDER BY s.message_count DESC
        LIMIT 500
        """,
        sp,
    )


def forgotten_sessions(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, silent_days: int = 90
) -> pd.DataFrame:
    sw, sp = _session_where(f)
    return _query_df(
        conn,
        f"""
        WITH latest AS (
            SELECT max(coalesce(updated_at_local, created_at_local))::DATE AS max_day
            FROM cursor_history.sessions
        )
        SELECT
            s.session_id,
            s.title,
            s.source_kind,
            s.message_count,
            coalesce(s.updated_at_local, s.created_at_local)::DATE AS last_day,
            date_diff(
                'day',
                coalesce(s.updated_at_local, s.created_at_local)::DATE,
                (SELECT max_day FROM latest)
            ) AS days_silent
        FROM cursor_history.sessions s
        WHERE {sw}
          AND coalesce(s.updated_at_local, s.created_at_local) IS NOT NULL
          AND date_diff(
                'day',
                coalesce(s.updated_at_local, s.created_at_local)::DATE,
                (SELECT max_day FROM latest)
              ) >= ?
        ORDER BY days_silent DESC
        LIMIT 40
        """,
        [*sp, silent_days],
    )


def comeback_sessions(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Sessions with a ≥30-day gap between first and last message activity."""
    mw, mp = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH bounds AS (
            SELECT
                m.session_id,
                min(m.created_at_local)::DATE AS first_day,
                max(m.created_at_local)::DATE AS last_day,
                count(*)::BIGINT AS n_messages
            FROM cursor_history.messages m
            WHERE {mw}
            GROUP BY 1
        )
        SELECT
            b.session_id,
            s.title,
            b.first_day,
            b.last_day,
            date_diff('day', b.first_day, b.last_day) AS span_days,
            b.n_messages
        FROM bounds b
        JOIN cursor_history.sessions s ON s.session_id = b.session_id
        WHERE date_diff('day', b.first_day, b.last_day) >= 30
        ORDER BY span_days DESC
        LIMIT 40
        """,
        mp,
    )


def project_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _session_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(project_slug, '(none)') AS project_slug,
            count(*)::BIGINT AS sessions,
            coalesce(sum(message_count), 0)::BIGINT AS messages
        FROM cursor_history.sessions s
        WHERE {where}
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 25
        """,
        params,
    )


def role_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT role, count(*)::BIGINT AS messages
        FROM cursor_history.messages m
        WHERE {where}
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        params,
    )


def session_messages(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 400
) -> pd.DataFrame:
    if not f.session_id:
        return pd.DataFrame()
    return _query_df(
        conn,
        """
        SELECT
            ordinal,
            role,
            created_at_local,
            model,
            char_count,
            left(coalesce(text, ''), 2000) AS text_preview,
            has_thinking,
            has_diff
        FROM cursor_history.messages
        WHERE session_id = ?
        ORDER BY ordinal
        LIMIT ?
        """,
        [f.session_id, limit],
    )


_TOOL_FAMILY_SQL = """
CASE
  WHEN lower(coalesce(t.tool_name, '')) LIKE 'read_file%'
    OR lower(coalesce(t.tool_name, '')) IN ('read', 'readfile')
    THEN 'read'
  WHEN lower(coalesce(t.tool_name, '')) LIKE 'edit_file%'
    OR lower(coalesce(t.tool_name, '')) IN ('search_replace', 'write', 'apply_patch')
    THEN 'edit'
  WHEN lower(coalesce(t.tool_name, '')) LIKE '%grep%'
    OR lower(coalesce(t.tool_name, '')) LIKE 'ripgrep%'
    OR lower(coalesce(t.tool_name, '')) LIKE '%search%'
    OR lower(coalesce(t.tool_name, '')) LIKE 'glob%'
    THEN 'search'
  WHEN lower(coalesce(t.tool_name, '')) LIKE '%terminal%'
    OR lower(coalesce(t.tool_name, '')) IN ('shell', 'bash', 'run_terminal_cmd')
    THEN 'shell'
  WHEN lower(coalesce(t.tool_name, '')) LIKE 'todo%'
    THEN 'todo'
  WHEN lower(coalesce(t.tool_name, '')) LIKE '%mcp%'
    OR lower(coalesce(t.tool_name, '')) LIKE 'call_mcp%'
    OR lower(coalesce(t.tool_name, '')) LIKE 'get_mcp%'
    THEN 'mcp'
  WHEN lower(coalesce(t.tool_name, '')) LIKE 'task%'
    OR lower(coalesce(t.tool_name, '')) LIKE '%subagent%'
    THEN 'task'
  WHEN t.tool_name IS NULL OR t.tool_name = '' THEN 'unknown'
  ELSE 'other'
END
"""


def tool_family_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    sw, sp = _session_where(f)
    return _query_df(
        conn,
        f"""
        SELECT {_TOOL_FAMILY_SQL} AS tool_family, count(*)::BIGINT AS tool_calls
        FROM cursor_history.tool_calls t
        WHERE exists (
            SELECT 1 FROM cursor_history.sessions s
            WHERE s.session_id = t.session_id AND {sw}
        )
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        sp,
    )


def tools_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    sw, sp = _session_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', m.year::INT, m.month::INT) AS year_month,
            {_TOOL_FAMILY_SQL} AS tool_family,
            count(*)::BIGINT AS tool_calls
        FROM cursor_history.tool_calls t
        JOIN cursor_history.messages m
          ON m.session_id = t.session_id AND m.message_id = t.message_id
        WHERE m.year IS NOT NULL AND m.month IS NOT NULL
          AND exists (
            SELECT 1 FROM cursor_history.sessions s
            WHERE s.session_id = t.session_id AND {sw}
          )
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        sp,
    )


def tool_family_rank_bump(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, top_n: int = 6
) -> pd.DataFrame:
    sw, sp = _session_where(f)
    return _query_df(
        conn,
        f"""
        WITH yearly AS (
            SELECT
                m.year::INT AS year,
                {_TOOL_FAMILY_SQL} AS tool_family,
                count(*)::BIGINT AS tool_calls
            FROM cursor_history.tool_calls t
            JOIN cursor_history.messages m
              ON m.session_id = t.session_id AND m.message_id = t.message_id
            WHERE m.year IS NOT NULL
              AND exists (
                SELECT 1 FROM cursor_history.sessions s
                WHERE s.session_id = t.session_id AND {sw}
              )
            GROUP BY 1, 2
        ),
        ranked AS (
            SELECT
                year,
                tool_family,
                tool_calls,
                row_number() OVER (PARTITION BY year ORDER BY tool_calls DESC) AS rank
            FROM yearly
        ),
        keep AS (
            SELECT tool_family FROM ranked WHERE rank <= ? GROUP BY 1
        )
        SELECT r.year, r.tool_family, r.tool_calls, r.rank
        FROM ranked r
        JOIN keep k ON k.tool_family = r.tool_family
        ORDER BY r.year, r.rank
        """,
        [*sp, top_n],
    )


def unified_mode_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _session_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(unified_mode, '(none)') AS unified_mode,
            count(*)::BIGINT AS sessions,
            coalesce(sum(message_count), 0)::BIGINT AS messages
        FROM cursor_history.sessions s
        WHERE {where}
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        params,
    )


def subagent_type_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _session_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(subagent_type, '(none)') AS subagent_type,
            count(*)::BIGINT AS sessions
        FROM cursor_history.sessions s
        WHERE {where} AND s.is_subagent
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 20
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
            FROM cursor_history.messages m
            WHERE {where} AND role = 'user'
        )
        SELECT bucket, count(*)::BIGINT AS messages
        FROM tagged
        GROUP BY bucket, ord
        ORDER BY ord
        """,
        params,
    )


def session_depth(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _session_where(f)
    return _query_df(
        conn,
        f"""
        WITH tagged AS (
            SELECT
                CASE
                    WHEN coalesce(message_count, 0) <= 2 THEN 1
                    WHEN message_count <= 10 THEN 2
                    WHEN message_count <= 40 THEN 3
                    WHEN message_count <= 120 THEN 4
                    ELSE 5
                END AS ord,
                CASE
                    WHEN coalesce(message_count, 0) <= 2 THEN '1–2'
                    WHEN message_count <= 10 THEN '3–10'
                    WHEN message_count <= 40 THEN '11–40'
                    WHEN message_count <= 120 THEN '41–120'
                    ELSE '121+'
                END AS bucket
            FROM cursor_history.sessions s
            WHERE {where}
        )
        SELECT bucket, count(*)::BIGINT AS sessions
        FROM tagged
        GROUP BY bucket, ord
        ORDER BY ord
        """,
        params,
    )


def tool_density(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Sessions by tools-per-message buckets (agentic intensity)."""
    where, params = _session_where(f)
    return _query_df(
        conn,
        f"""
        WITH tagged AS (
            SELECT
                CASE
                    WHEN coalesce(message_count, 0) = 0 THEN 0
                    ELSE tool_call_count::DOUBLE / message_count
                END AS density
            FROM cursor_history.sessions s
            WHERE {where}
        ),
        bucketed AS (
            SELECT
                CASE
                    WHEN density = 0 THEN 1
                    WHEN density < 0.25 THEN 2
                    WHEN density < 0.75 THEN 3
                    WHEN density < 1.5 THEN 4
                    ELSE 5
                END AS ord,
                CASE
                    WHEN density = 0 THEN '0'
                    WHEN density < 0.25 THEN '<0.25'
                    WHEN density < 0.75 THEN '0.25–0.74'
                    WHEN density < 1.5 THEN '0.75–1.49'
                    ELSE '1.5+'
                END AS bucket
            FROM tagged
        )
        SELECT bucket, count(*)::BIGINT AS sessions
        FROM bucketed
        GROUP BY bucket, ord
        ORDER BY ord
        """,
        params,
    )


def search_messages(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 80,
) -> pd.DataFrame:
    """Bound-parameter substring search over message text (+ optional title)."""
    if not f.text_search:
        return pd.DataFrame()
    mw, mp = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            m.session_id,
            s.title,
            m.ordinal,
            m.role,
            m.created_at_local,
            m.char_count,
            left(coalesce(m.text, ''), 400) AS snippet
        FROM cursor_history.messages m
        JOIN cursor_history.sessions s ON s.session_id = m.session_id
        WHERE {mw}
        ORDER BY m.created_at_local DESC NULLS LAST
        LIMIT ?
        """,
        [*mp, limit],
    )


def reply_latency(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """User → next assistant latency (minutes) within a session."""
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH ordered AS (
            SELECT
                session_id,
                role,
                created_at_local,
                lead(role) OVER (
                    PARTITION BY session_id ORDER BY ordinal, created_at_local
                ) AS next_role,
                lead(created_at_local) OVER (
                    PARTITION BY session_id ORDER BY ordinal, created_at_local
                ) AS next_ts
            FROM cursor_history.messages m
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


def narrative_context(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> dict[str, Any]:
    score = scoreboard(conn, f)
    streak = streak_stats(conn, f)
    return {
        "filter_digest": f.filter_digest(),
        "filters": {k: v for k, v in f.__dict__.items()},
        "scoreboard": score.to_dict(orient="records"),
        "streak": streak.to_dict(orient="records"),
        "source_mix": source_kind_mix(conn, f).to_dict(orient="records"),
        "tool_mix": tool_name_mix(conn, f).head(10).to_dict(orient="records"),
        "top_sessions": top_sessions(conn, f, limit=10).to_dict(orient="records"),
        "forgotten": forgotten_sessions(conn, f).head(5).to_dict(orient="records"),
        "comebacks": comeback_sessions(conn, f).head(5).to_dict(orient="records"),
        "depth": session_depth(conn, f).to_dict(orient="records"),
        "length_buckets": message_length_buckets(conn, f).to_dict(orient="records"),
        "mode_mix": unified_mode_mix(conn, f).to_dict(orient="records"),
    }
