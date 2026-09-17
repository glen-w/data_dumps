"""Filter state and DuckDB queries for the LinkedIn Marimo dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util


@dataclass
class FilterState:
    """Year-range filter for LinkedIn explorer queries."""

    year_start: int | None = None
    year_end: int | None = None
    conversation: str | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        if self.conversation:
            chips.append(("conversation", f"chat: {self.conversation}"))
        return chips


def _year_clause(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    return query_util.year_clause(alias, f.year_start, f.year_end)


def _msg_where(f: FilterState, alias: str = "") -> tuple[str, list[Any]]:
    where, params = _year_clause(alias, f)
    p = f"{alias}." if alias else ""
    if f.conversation:
        where = (
            f"({where}) AND coalesce(nullif({p}conversation_title, ''), "
            f"{p}conversation_id) = ?"
        )
        params = [*params, f.conversation]
    return where, params


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    conversation: str | None = None,
) -> FilterState:
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    conv = conversation.strip() if conversation else None
    return FilterState(year_start=ys, year_end=ye, conversation=conv or None)


def previous_window(f: FilterState) -> FilterState | None:
    bounds = query_util.previous_year_bounds(f.year_start, f.year_end)
    if bounds is None:
        return None
    return FilterState(
        year_start=bounds[0],
        year_end=bounds[1],
        conversation=f.conversation,
    )


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def has_table(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return query_util.has_table(conn, "linkedin", table)


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


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    c_where, c_params = _year_clause("c", f)
    m_where, m_params = _msg_where(f, "m")
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
    params = [
        *c_params,
        *m_params,
        *m_params,
        *r_params,
        *s_params,
        *k_params,
    ]
    return _query_df(conn, sql, params)


def scoreboard(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    compare_previous: bool = False,
) -> pd.DataFrame:
    current = _scoreboard_row(conn, f)
    current["window"] = "current"
    if not compare_previous:
        return current
    prev_f = previous_window(f)
    if prev_f is None:
        return current
    prev = _scoreboard_row(conn, prev_f)
    prev["window"] = f"previous ({prev_f.year_start}–{prev_f.year_end})"
    return pd.concat([current, prev], ignore_index=True)


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


def connections_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS connections
        FROM linkedin.connections
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY year, month
        ORDER BY year, month
        """,
        params,
    )


def calendar_daily_connections(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT connected_on AS day, count(*)::BIGINT AS connections
        FROM linkedin.connections
        WHERE {where} AND connected_on IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def reactions_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS reactions
        FROM linkedin.reactions
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY year, month
        ORDER BY year, month
        """,
        params,
    )


def calendar_daily_reactions(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT ts_local::DATE AS day, count(*)::BIGINT AS reactions
        FROM linkedin.reactions
        WHERE {where} AND ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def shares_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS shares
        FROM linkedin.shares
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY year, month
        ORDER BY year, month
        """,
        params,
    )


def calendar_daily_shares(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT ts_local::DATE AS day, count(*)::BIGINT AS shares
        FROM linkedin.shares
        WHERE {where} AND ts_local IS NOT NULL
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


def positions_by_location(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Distinct career locations with role counts (for geo map)."""
    return _query_df(
        conn,
        """
        SELECT
            location AS city,
            count(*)::BIGINT AS roles,
            count(DISTINCT company_name)::BIGINT AS companies
        FROM linkedin.positions
        WHERE location IS NOT NULL AND trim(location) <> ''
        GROUP BY 1
        ORDER BY roles DESC, city
        """,
    )


def messages_by_conversation(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    # Rankings ignore conversation lock so the picker still lists peers.
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
    where, params = _msg_where(f)
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
    where, params = _msg_where(f)
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
    where, params = _msg_where(f)
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


def message_streaks(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH daily AS (
            SELECT ts_local::DATE AS day
            FROM linkedin.messages
            WHERE {where} AND ts_local IS NOT NULL
            GROUP BY 1
        ),
        ordered AS (
            SELECT
                day,
                day - (row_number() OVER (ORDER BY day))::INT AS grp
            FROM daily
        ),
        streaks AS (
            SELECT count(*)::BIGINT AS streak_len, max(day) AS last_d
            FROM ordered
            GROUP BY grp
        )
        SELECT
            coalesce(max(streak_len), 0)::BIGINT AS longest_active_streak,
            coalesce(
                (SELECT streak_len FROM streaks ORDER BY last_d DESC LIMIT 1),
                0
            )::BIGINT AS current_active_streak
        FROM streaks
        """,
        params,
    )


def monthly_messages(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    df = _query_df(
        conn,
        f"""
        SELECT
            year,
            month,
            count(*)::BIGINT AS messages,
            count(*) FILTER (WHERE is_from_me)::BIGINT AS from_me,
            count(*) FILTER (WHERE NOT is_from_me)::BIGINT AS from_them
        FROM linkedin.messages
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )
    if not df.empty:
        df["year_month"] = (
            df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
        )
    return df


def conversation_scatter(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(nullif(conversation_title, ''), conversation_id) AS conversation,
            count(*)::BIGINT AS messages,
            round(
                100.0 * count(*) FILTER (WHERE is_from_me) / nullif(count(*), 0),
                1
            ) AS me_pct,
            max(ts_utc)::DATE AS last_day
        FROM linkedin.messages
        WHERE {where}
        GROUP BY 1
        HAVING count(*) >= 2
        ORDER BY messages DESC
        """,
        params,
    )


def forgotten_conversations(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    min_messages: int = 2,
    silent_years: int = 1,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    params.extend([min_messages, silent_years, limit])
    return _query_df(
        conn,
        f"""
        WITH span AS (
            SELECT
                coalesce(nullif(conversation_title, ''), conversation_id) AS conversation,
                count(*)::BIGINT AS messages,
                max(ts_utc) AS last_ts
            FROM linkedin.messages
            WHERE {where}
            GROUP BY 1
            HAVING count(*) >= ?
        )
        SELECT conversation, messages, last_ts::DATE AS last_day
        FROM span
        WHERE last_ts < current_timestamp - (? * INTERVAL '1 year')
        ORDER BY messages DESC
        LIMIT ?
        """,
        params,
    )


def comeback_conversations(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    silent_years: int = 1,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _year_clause("", f)
    params.extend([silent_years, limit])
    return _query_df(
        conn,
        f"""
        WITH filtered AS (
            SELECT
                coalesce(nullif(conversation_title, ''), conversation_id) AS conversation,
                conversation_id,
                ts_utc
            FROM linkedin.messages
            WHERE {where}
        ),
        span AS (
            SELECT
                conversation,
                conversation_id,
                min(ts_utc) AS first_in_window,
                count(*)::BIGINT AS window_messages
            FROM filtered
            GROUP BY 1, 2
        ),
        prior AS (
            SELECT
                m.conversation_id,
                max(m.ts_utc) AS last_before
            FROM linkedin.messages m
            INNER JOIN span a ON m.conversation_id = a.conversation_id
            WHERE m.ts_utc < a.first_in_window
            GROUP BY 1
        )
        SELECT
            a.conversation,
            a.window_messages,
            p.last_before::DATE AS last_before,
            round(date_diff('day', p.last_before, a.first_in_window) / 365.25, 1)
                AS gap_years
        FROM span a
        INNER JOIN prior p ON a.conversation_id = p.conversation_id
        WHERE p.last_before < a.first_in_window - (? * INTERVAL '1 year')
        ORDER BY a.window_messages DESC
        LIMIT ?
        """,
        params,
    )


def conversation_rank_bump(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 10
) -> pd.DataFrame:
    """Yearly rank of top conversations (for bump chart)."""
    where, params = _year_clause("", f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        WITH yearly AS (
            SELECT
                year,
                coalesce(nullif(conversation_title, ''), conversation_id) AS conversation,
                count(*)::BIGINT AS messages
            FROM linkedin.messages
            WHERE {where} AND year IS NOT NULL
            GROUP BY 1, 2
        ),
        ranked AS (
            SELECT
                year,
                conversation,
                messages,
                row_number() OVER (PARTITION BY year ORDER BY messages DESC) AS rank
            FROM yearly
        )
        SELECT year, conversation, messages, rank
        FROM ranked
        WHERE rank <= ?
        ORDER BY year, rank
        """,
        params,
    )


def invitation_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    if not has_table(conn, "invitations"):
        return pd.DataFrame(columns=["direction", "year", "invites"])
    where, params = _year_clause("", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(direction, '(unknown)') AS direction,
            year,
            count(*)::BIGINT AS invites
        FROM linkedin.invitations
        WHERE {where} AND year IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 2, 1
        """,
        params,
    )


def endorsement_counts(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if has_table(conn, "endorsements_given"):
        where, params = _year_clause("", f)
        given = _query_df(
            conn,
            f"""
            SELECT count(*)::BIGINT AS n
            FROM linkedin.endorsements_given
            WHERE {where}
            """,
            params,
        )
        rows.append(
            {
                "kind": "given",
                "count": int(given.iloc[0]["n"]) if not given.empty else 0,
            }
        )
    if has_table(conn, "endorsements_received"):
        where, params = _year_clause("", f)
        recv = _query_df(
            conn,
            f"""
            SELECT count(*)::BIGINT AS n
            FROM linkedin.endorsements_received
            WHERE {where}
            """,
            params,
        )
        rows.append(
            {
                "kind": "received",
                "count": int(recv.iloc[0]["n"]) if not recv.empty else 0,
            }
        )
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["kind", "count"])


def events_summary(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    if not has_table(conn, "events"):
        return pd.DataFrame(columns=["event_name", "ts"])
    where, params = _year_clause("", f)
    params.append(limit)
    # Column names vary; pick common ones defensively via information_schema
    cols = {r[0] for r in conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'linkedin' AND table_name = 'events'
            """).fetchall()}
    name_col = (
        "event_name" if "event_name" in cols else ("name" if "name" in cols else None)
    )
    if name_col is None:
        return pd.DataFrame(columns=["event_name", "ts"])
    ts_col = (
        "ts_utc" if "ts_utc" in cols else ("ts_local" if "ts_local" in cols else None)
    )
    if ts_col is None:
        return _query_df(
            conn,
            f"""
            SELECT {name_col} AS event_name, NULL::TIMESTAMP AS ts
            FROM linkedin.events
            WHERE {where}
            LIMIT ?
            """,
            params,
        )
    return _query_df(
        conn,
        f"""
        SELECT {name_col} AS event_name, {ts_col} AS ts
        FROM linkedin.events
        WHERE {where}
        ORDER BY {ts_col} DESC NULLS LAST
        LIMIT ?
        """,
        params,
    )


def learning_summary(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    if not has_table(conn, "learning"):
        return pd.DataFrame(columns=["title", "ts"])
    where, params = _year_clause("", f)
    params.append(limit)
    cols = {r[0] for r in conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'linkedin' AND table_name = 'learning'
            """).fetchall()}
    title_col = (
        "title"
        if "title" in cols
        else ("content_title" if "content_title" in cols else None)
    )
    if title_col is None:
        return pd.DataFrame(columns=["title", "ts"])
    ts_col = (
        "ts_utc" if "ts_utc" in cols else ("ts_local" if "ts_local" in cols else None)
    )
    if ts_col is None:
        return _query_df(
            conn,
            f"SELECT {title_col} AS title, NULL::TIMESTAMP AS ts FROM linkedin.learning "
            f"WHERE {where} LIMIT ?",
            params,
        )
    return _query_df(
        conn,
        f"""
        SELECT {title_col} AS title, {ts_col} AS ts
        FROM linkedin.learning
        WHERE {where}
        ORDER BY {ts_col} DESC NULLS LAST
        LIMIT ?
        """,
        params,
    )
