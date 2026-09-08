"""Filter state and DuckDB queries for the LinkedIn Marimo dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd


@dataclass
class FilterState:
    """Year-range filter for LinkedIn explorer queries."""

    year_start: int | None = None
    year_end: int | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        return chips


def _year_clause(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    prefix = f"{alias}." if alias else ""
    if f.year_start is not None:
        clauses.append(f"{prefix}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{prefix}year <= ?")
        params.append(f.year_end)
    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def has_table(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = conn.execute(
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'linkedin' AND table_name = ?
        """,
        [table],
    ).fetchone()
    return row is not None and row[0] > 0


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT AS min_year,
            max(year)::INT AS max_year,
            min(d)::DATE AS first_day,
            max(d)::DATE AS last_day
        FROM (
            SELECT year, connected_on AS d FROM linkedin.connections
            UNION ALL
            SELECT year, ts_utc::DATE FROM linkedin.messages
            UNION ALL
            SELECT year, ts_utc::DATE FROM linkedin.reactions
        )
        """).fetchone()
    assert row is not None
    min_year = row[0]
    max_year = row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2010, 2026
    me = conn.execute("SELECT display_name FROM linkedin.account").fetchone()
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "display_name": me[0] if me else None,
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
) -> FilterState:
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    return FilterState(year_start=ys, year_end=ye)


def scoreboard(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    c_where, c_params = _year_clause("c", f)
    m_where, m_params = _year_clause("m", f)
    r_where, r_params = _year_clause("r", f)
    s_where, s_params = _year_clause("s", f)
    k_where, k_params = _year_clause("k", f)
    sql = f"""
        SELECT
            (SELECT count(*)::BIGINT FROM linkedin.connections c WHERE {c_where})
                AS connections,
            (SELECT count(*)::BIGINT FROM linkedin.messages m WHERE {m_where})
                AS messages,
            (SELECT count(DISTINCT m.conversation_id)::BIGINT
             FROM linkedin.messages m WHERE {m_where}) AS conversations,
            (SELECT count(*)::BIGINT FROM linkedin.reactions r WHERE {r_where})
                AS reactions,
            (SELECT count(*)::BIGINT FROM linkedin.shares s WHERE {s_where})
                AS shares,
            (SELECT count(*)::BIGINT FROM linkedin.comments k WHERE {k_where})
                AS comments
    """
    params = [*c_params, *m_params, *m_params, *r_params, *s_params, *k_params]
    return _query_df(conn, sql, params)


def connections_by_year(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT year, count(*)::BIGINT AS connections
        FROM linkedin.connections
        WHERE {where} AND year IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def top_connection_companies(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT company, count(*)::BIGINT AS connections
        FROM linkedin.connections
        WHERE {where} AND company IS NOT NULL AND company <> ''
        GROUP BY 1
        ORDER BY connections DESC
        LIMIT ?
        """,
        params,
    )


def top_connection_titles(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT position AS title, count(*)::BIGINT AS connections
        FROM linkedin.connections
        WHERE {where} AND position IS NOT NULL AND position <> ''
        GROUP BY 1
        ORDER BY connections DESC
        LIMIT ?
        """,
        params,
    )


def career_timeline(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            'position' AS kind,
            company_name AS org,
            title AS detail,
            started_on AS start_label,
            finished_on AS end_label,
            start_year,
            end_year
        FROM linkedin.positions
        UNION ALL
        SELECT
            'education' AS kind,
            school_name AS org,
            degree_name AS detail,
            start_date AS start_label,
            end_date AS end_label,
            start_year,
            end_year
        FROM linkedin.education
        ORDER BY start_year NULLS LAST, kind
        """,
    )


def messages_by_conversation(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(nullif(conversation_title, ''), conversation_id) AS conversation,
            count(*)::BIGINT AS messages,
            count(*) FILTER (WHERE is_from_me)::BIGINT AS from_me,
            count(*) FILTER (WHERE NOT is_from_me)::BIGINT AS from_them,
            min(ts_utc)::DATE AS first_day,
            max(ts_utc)::DATE AS last_day
        FROM linkedin.messages
        WHERE {where}
        GROUP BY 1
        ORDER BY messages DESC
        LIMIT ?
        """,
        params,
    )


def me_vs_them(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT
            year,
            count(*) FILTER (WHERE is_from_me)::BIGINT AS me,
            count(*) FILTER (WHERE NOT is_from_me)::BIGINT AS them
        FROM linkedin.messages
        WHERE {where} AND year IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT ts_local::DATE AS day, count(*)::BIGINT AS events
        FROM linkedin.messages
        WHERE {where} AND ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def circadian_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT
            dayofweek(ts_local) AS dow,
            hour(ts_local) AS hour,
            count(*)::BIGINT AS events
        FROM linkedin.messages
        WHERE {where} AND ts_local IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def activity_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    r_where, r_params = _year_clause("", f)
    s_where, s_params = _year_clause("", f)
    c_where, c_params = _year_clause("", f)
    p_where, p_params = _year_clause("", f)
    sql = f"""
        SELECT kind, year, count(*)::BIGINT AS events
        FROM (
            SELECT 'reaction' AS kind, year FROM linkedin.reactions WHERE {r_where}
            UNION ALL
            SELECT 'share' AS kind, year FROM linkedin.shares WHERE {s_where}
            UNION ALL
            SELECT 'comment' AS kind, year FROM linkedin.comments WHERE {c_where}
            UNION ALL
            SELECT 'repost' AS kind, year FROM linkedin.reposts WHERE {p_where}
        )
        WHERE year IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 2, 1
    """
    return _query_df(conn, sql, [*r_params, *s_params, *c_params, *p_params])


def company_follows(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT organization, ts_utc::DATE AS followed_on
        FROM linkedin.company_follows
        WHERE {where}
        ORDER BY ts_utc DESC NULLS LAST
        LIMIT ?
        """,
        params,
    )
