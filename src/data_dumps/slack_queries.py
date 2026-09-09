"""Filter state and DuckDB queries for the Slack Marimo dashboard.

Two layers of "who":

* ``FilterState.user_ids`` narrows *every* query to those posters.
* ``person_*`` functions take an explicit ``user_id`` and compare that person
  against the rest of the team; they ignore ``f.user_ids`` so the baseline is
  not reduced to the person themself.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import duckdb
import pandas as pd

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
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
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
    if f.year_start is not None:
        clauses.append(f"{p}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{p}year <= ?")
        params.append(f.year_end)
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


# --------------------------------------------------------------------------- #
# Bounds / widgets


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


# --------------------------------------------------------------------------- #
# Workspace-level


def scoreboard(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, compare_previous: bool = False
) -> pd.DataFrame:
    current = _scoreboard_row(conn, f)
    current["window"] = "current"
    if not compare_previous or f.year_start is None or f.year_end is None:
        return current
    span = f.year_end - f.year_start + 1
    prev = replace(f, year_start=f.year_start - span, year_end=f.year_start - 1)
    prev_df = _scoreboard_row(conn, prev)
    prev_df["window"] = f"previous ({prev.year_start}–{prev.year_end})"
    return pd.concat([current, prev_df], ignore_index=True)


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS messages,
            count(DISTINCT m.user_id)::BIGINT AS people,
            count(DISTINCT m.channel_id)::BIGINT AS channels,
            count(*) FILTER (WHERE m.is_thread_root)::BIGINT AS threads,
            count(*) FILTER (WHERE m.is_reply)::BIGINT AS replies,
            round(100.0 * avg(CASE WHEN m.is_reply THEN 1.0 ELSE 0.0 END), 1)
                AS reply_pct,
            sum(m.n_reactions)::BIGINT AS reactions,
            sum(m.n_files)::BIGINT AS files,
            count(DISTINCT m.ts_local::DATE)::BIGINT AS active_days,
            min(m.ts_utc)::DATE AS first_day,
            max(m.ts_utc)::DATE AS last_day
        {_from_join()}
        WHERE {where}
        """,
        params,
    )


def monthly_messages_by_kind(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    """Human / bot / system volume per month (ignores bot/system toggles)."""
    base = replace(f, include_bots=True, include_system=True)
    where, params = _where(base)
    return _ym(
        _query_df(
            conn,
            f"""
        SELECT
            m.year, m.month,
            CASE
                WHEN m.is_bot THEN 'bot'
                WHEN m.subtype IN ('message', 'thread_broadcast') THEN 'human'
                ELSE 'system'
            END AS kind,
            count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
        """,
            params,
        )
    )


def active_people_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where(f)
    return _ym(
        _query_df(
            conn,
            f"""
        SELECT
            m.year, m.month,
            count(DISTINCT m.user_id)::BIGINT AS people,
            count(DISTINCT m.channel_id)::BIGINT AS channels,
            count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
            params,
        )
    )


def messages_by_channel(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT
            c.channel_id,
            c.name AS channel_name,
            c.kind,
            c.is_archived,
            count(*)::BIGINT AS messages,
            count(DISTINCT m.user_id)::BIGINT AS people,
            count(*) FILTER (WHERE m.is_thread_root)::BIGINT AS threads,
            round(100.0 * avg(CASE WHEN m.is_reply THEN 1.0 ELSE 0.0 END), 1)
                AS reply_pct,
            max(m.ts_utc)::DATE AS last_day
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2, 3, 4
        ORDER BY messages DESC
        LIMIT ?
        """,
        params,
    )


def bump_chart_channels(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, top_n: int = 8
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(top_n)
    return _query_df(
        conn,
        f"""
        WITH yearly AS (
            SELECT m.year, c.name AS channel_name, count(*)::BIGINT AS messages
            {_from_join()}
            WHERE {where}
            GROUP BY 1, 2
        ),
        top AS (
            SELECT channel_name FROM yearly
            GROUP BY 1 ORDER BY sum(messages) DESC LIMIT ?
        ),
        ranked AS (
            SELECT y.year, y.channel_name, y.messages,
                   row_number() OVER (PARTITION BY y.year ORDER BY y.messages DESC)
                       AS rank
            FROM yearly y JOIN top t USING (channel_name)
        )
        SELECT * FROM ranked ORDER BY year, rank
        """,
        params,
    )


def channel_lifecycle(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 40
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT
            c.name AS channel_name,
            c.kind,
            c.created_utc::DATE AS created,
            min(m.ts_utc)::DATE AS first_message,
            max(m.ts_utc)::DATE AS last_message,
            date_diff('day', min(m.ts_utc), max(m.ts_utc))::INT AS lifespan_days,
            count(*)::BIGINT AS messages,
            c.is_archived,
            c.n_members
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2, 3, 8, 9
        ORDER BY messages DESC
        LIMIT ?
        """,
        params,
    )


def channels_created_archived_by_year(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    """Channel births (created) and deaths (last message in archived channel)."""
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        WITH scoped AS (
            SELECT DISTINCT c.channel_id, c.created_utc, c.is_archived,
                   max(m.ts_utc) OVER (PARTITION BY c.channel_id) AS last_ts
            {_from_join()}
            WHERE {where}
        )
        SELECT year, sum(created)::BIGINT AS created, sum(archived)::BIGINT AS archived
        FROM (
            SELECT year(created_utc) AS year, 1 AS created, 0 AS archived
            FROM scoped WHERE created_utc IS NOT NULL
            UNION ALL
            SELECT year(last_ts), 0, 1 FROM scoped WHERE is_archived
        )
        GROUP BY 1 ORDER BY 1
        """,
        params,
    )


def forgotten_channels(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    min_messages: int = 50,
    silent_years: int = 2,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _where(f)
    params.extend([min_messages, silent_years, limit])
    return _query_df(
        conn,
        f"""
        WITH span AS (
            SELECT c.name AS channel_name, c.is_archived,
                   count(*)::BIGINT AS messages, max(m.ts_utc) AS last_ts
            {_from_join()}
            WHERE {where}
            GROUP BY 1, 2
            HAVING count(*) >= ?
        ),
        latest AS (SELECT max(ts_utc) AS export_end FROM slack.messages)
        SELECT channel_name, is_archived, messages, last_ts::DATE AS last_day
        FROM span, latest
        WHERE last_ts < export_end - (? * INTERVAL '1 year')
        ORDER BY messages DESC
        LIMIT ?
        """,
        params,
    )


def comeback_channels(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    silent_years: int = 1,
    limit: int = 25,
) -> pd.DataFrame:
    """Channels that were silent for >= ``silent_years`` and then posted again."""
    where, params = _where(f)
    params.extend([silent_years, limit])
    return _query_df(
        conn,
        f"""
        WITH scoped AS (
            SELECT m.channel_id, c.name AS channel_name, m.ts_utc
            {_from_join()}
            WHERE {where}
        ),
        ordered AS (
            SELECT channel_id, channel_name, ts_utc,
                   lag(ts_utc) OVER (PARTITION BY channel_id ORDER BY ts_utc) AS prev_ts
            FROM scoped
        ),
        gaps AS (
            SELECT channel_id, channel_name,
                   prev_ts AS silent_from, ts_utc AS returned_on,
                   date_diff('day', prev_ts, ts_utc) AS gap_days
            FROM ordered
            WHERE prev_ts IS NOT NULL
              AND ts_utc >= prev_ts + (? * INTERVAL '1 year')
        ),
        best AS (
            SELECT channel_id, channel_name,
                   max(gap_days)::INT AS longest_gap_days,
                   arg_max(silent_from, gap_days)::DATE AS silent_from,
                   arg_max(returned_on, gap_days)::DATE AS returned_on,
                   count(*)::BIGINT AS comebacks
            FROM gaps GROUP BY 1, 2
        ),
        totals AS (
            SELECT channel_id, count(*)::BIGINT AS messages FROM scoped GROUP BY 1
        )
        SELECT b.channel_name, b.longest_gap_days, b.silent_from, b.returned_on,
               b.comebacks, t.messages
        FROM best b JOIN totals t USING (channel_id)
        ORDER BY b.longest_gap_days DESC
        LIMIT ?
        """,
        params,
    )


def top_people(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT
            m.user_id,
            coalesce(u.real_name, u.display_name, m.user_name, m.user_id) AS name,
            u.deleted,
            count(*)::BIGINT AS messages,
            count(*) FILTER (WHERE m.is_thread_root)::BIGINT AS threads_started,
            count(*) FILTER (WHERE m.is_reply)::BIGINT AS replies,
            sum(m.n_reactions)::BIGINT AS reactions_received,
            count(DISTINCT m.channel_id)::BIGINT AS channels,
            count(DISTINCT m.ts_local::DATE)::BIGINT AS active_days,
            min(m.ts_utc)::DATE AS first_day,
            max(m.ts_utc)::DATE AS last_day
        {_from_join()}
        LEFT JOIN slack.users u ON u.user_id = m.user_id
        WHERE {where}
        GROUP BY 1, 2, 3
        ORDER BY messages DESC
        LIMIT ?
        """,
        params,
    )


def bump_chart_people(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, top_n: int = 8
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(top_n)
    return _query_df(
        conn,
        f"""
        WITH yearly AS (
            SELECT m.year, m.user_name AS name, count(*)::BIGINT AS messages
            {_from_join()}
            WHERE {where}
            GROUP BY 1, 2
        ),
        top AS (SELECT name FROM yearly GROUP BY 1 ORDER BY sum(messages) DESC LIMIT ?),
        ranked AS (
            SELECT y.year, y.name, y.messages,
                   row_number() OVER (PARTITION BY y.year ORDER BY y.messages DESC)
                       AS rank
            FROM yearly y JOIN top t USING (name)
        )
        SELECT * FROM ranked ORDER BY year, rank
        """,
        params,
    )


def people_reply_ratio(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    """Root posts vs replies vs reactions given, per person."""
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        WITH base AS (
            SELECT m.user_id, m.user_name, m.channel_id, m.ts, m.is_reply
            {_from_join()}
            WHERE {where}
        ),
        posts AS (
            SELECT user_id, any_value(user_name) AS name,
                   count(*) FILTER (WHERE NOT is_reply)::BIGINT AS root_posts,
                   count(*) FILTER (WHERE is_reply)::BIGINT AS replies
            FROM base GROUP BY 1
        ),
        reacts AS (
            SELECT r.user_id, count(*)::BIGINT AS reactions_given
            FROM slack.reactions r
            JOIN base b ON b.channel_id = r.channel_id AND b.ts = r.ts
            GROUP BY 1
        )
        SELECT p.name, p.root_posts, p.replies,
               coalesce(r.reactions_given, 0) AS reactions_given,
               round(100.0 * p.replies / nullif(p.root_posts + p.replies, 0), 1)
                   AS reply_share_pct
        FROM posts p LEFT JOIN reacts r USING (user_id)
        ORDER BY (p.root_posts + p.replies) DESC
        LIMIT ?
        """,
        params,
    )


def thread_depth_distribution(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            CASE
                WHEN m.reply_count >= 20 THEN '20+'
                WHEN m.reply_count >= 10 THEN '10-19'
                WHEN m.reply_count >= 5 THEN '5-9'
                ELSE m.reply_count::VARCHAR
            END AS depth,
            min(m.reply_count) AS sort_key,
            count(*)::BIGINT AS threads
        {_from_join()}
        WHERE {where} AND m.is_thread_root
        GROUP BY 1
        ORDER BY sort_key
        """,
        params,
    )


def _reply_latency_cte(where: str) -> str:
    return f"""
        WITH roots AS (
            SELECT m.channel_id, m.ts, m.ts_utc, m.user_id, c.name AS channel_name
            {_from_join()}
            WHERE {where} AND m.is_thread_root
        ),
        first_reply AS (
            SELECT r.channel_id, r.ts, r.ts_utc, r.user_id, r.channel_name,
                   min(x.ts_utc) AS first_reply_utc
            FROM roots r
            JOIN slack.messages x
              ON x.channel_id = r.channel_id AND x.thread_ts = r.ts AND x.is_reply
            GROUP BY 1, 2, 3, 4, 5
        ),
        latency AS (
            SELECT channel_name, user_id,
                   date_diff('second', ts_utc, first_reply_utc) / 60.0 AS minutes
            FROM first_reply
        )
    """


def reply_latency(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Overall time-to-first-reply distribution (minutes)."""
    where, params = _where(f)
    return _query_df(
        conn,
        _reply_latency_cte(where)
        + """
        SELECT
            count(*)::BIGINT AS threads,
            round(quantile_cont(minutes, 0.5), 1) AS median_min,
            round(quantile_cont(minutes, 0.9), 1) AS p90_min,
            round(100.0 * avg(CASE WHEN minutes <= 60 THEN 1.0 ELSE 0.0 END), 1)
                AS within_1h_pct,
            round(100.0 * avg(CASE WHEN minutes <= 1440 THEN 1.0 ELSE 0.0 END), 1)
                AS within_24h_pct
        FROM latency
        """,
        params,
    )


def reply_latency_by_channel(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    min_threads: int = 10,
    limit: int = 20,
) -> pd.DataFrame:
    where, params = _where(f)
    params.extend([min_threads, limit])
    return _query_df(
        conn,
        _reply_latency_cte(where)
        + """
        SELECT channel_name,
               count(*)::BIGINT AS threads,
               round(quantile_cont(minutes, 0.5), 1) AS median_min,
               round(quantile_cont(minutes, 0.9), 1) AS p90_min
        FROM latency
        GROUP BY 1
        HAVING count(*) >= ?
        ORDER BY threads DESC
        LIMIT ?
        """,
        params,
    )


def busiest_threads(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 15
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT
            m.ts_local::DATE AS day,
            c.name AS channel_name,
            m.user_name,
            m.reply_count,
            m.reply_users_count,
            m.n_reactions,
            left(m.text, 140) AS text
        {_from_join()}
        WHERE {where} AND m.is_thread_root
        ORDER BY m.reply_count DESC, m.n_reactions DESC
        LIMIT ?
        """,
        params,
    )


def reaction_mix(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT r.emoji, count(*)::BIGINT AS reactions
        FROM slack.reactions r
        JOIN slack.messages m ON m.channel_id = r.channel_id AND m.ts = r.ts
        JOIN slack.channels c ON c.channel_id = m.channel_id
        WHERE {where}
        GROUP BY 1
        ORDER BY reactions DESC
        LIMIT ?
        """,
        params,
    )


def most_reacted_messages(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 15
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT
            m.ts_local::DATE AS day,
            c.name AS channel_name,
            m.user_name,
            m.n_reactions,
            m.reply_count,
            left(m.text, 140) AS text
        {_from_join()}
        WHERE {where} AND m.n_reactions > 0
        ORDER BY m.n_reactions DESC, m.reply_count DESC
        LIMIT ?
        """,
        params,
    )


def top_reactors(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 15
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(u.real_name, u.display_name, u.handle, r.user_id) AS name,
            count(*)::BIGINT AS reactions_given,
            count(DISTINCT r.emoji)::BIGINT AS distinct_emoji,
            mode(r.emoji) AS favourite_emoji
        FROM slack.reactions r
        JOIN slack.messages m ON m.channel_id = r.channel_id AND m.ts = r.ts
        JOIN slack.channels c ON c.channel_id = m.channel_id
        LEFT JOIN slack.users u ON u.user_id = r.user_id
        WHERE {where} AND r.user_id IS NOT NULL
        GROUP BY 1
        ORDER BY reactions_given DESC
        LIMIT ?
        """,
        params,
    )


def top_mentioned(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 15
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(u.real_name, u.display_name, u.handle, mt.mentioned_user_id)
                AS name,
            count(*)::BIGINT AS mentions,
            count(DISTINCT m.user_id)::BIGINT AS mentioned_by_people
        FROM slack.mentions mt
        JOIN slack.messages m ON m.channel_id = mt.channel_id AND m.ts = mt.ts
        JOIN slack.channels c ON c.channel_id = m.channel_id
        LEFT JOIN slack.users u ON u.user_id = mt.mentioned_user_id
        WHERE {where}
        GROUP BY 1
        ORDER BY mentions DESC
        LIMIT ?
        """,
        params,
    )


def mention_pairs(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    where, params = _where(f)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT
            m.user_name AS from_name,
            coalesce(u.real_name, u.display_name, u.handle, mt.mentioned_user_id)
                AS to_name,
            count(*)::BIGINT AS mentions
        FROM slack.mentions mt
        JOIN slack.messages m ON m.channel_id = mt.channel_id AND m.ts = mt.ts
        JOIN slack.channels c ON c.channel_id = m.channel_id
        LEFT JOIN slack.users u ON u.user_id = mt.mentioned_user_id
        WHERE {where} AND mt.mentioned_user_id IS DISTINCT FROM m.user_id
        GROUP BY 1, 2
        ORDER BY mentions DESC
        LIMIT ?
        """,
        params,
    )


def bots_by_name(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 15
) -> pd.DataFrame:
    base = replace(f, include_bots=True, include_system=True)
    where, params = _where(base)
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(m.bot_name, m.user_name, m.bot_id, 'unknown bot') AS bot,
            count(*)::BIGINT AS messages,
            count(DISTINCT m.channel_id)::BIGINT AS channels,
            min(m.ts_utc)::DATE AS first_day,
            max(m.ts_utc)::DATE AS last_day
        {_from_join()}
        WHERE {where} AND m.is_bot
        GROUP BY 1
        ORDER BY messages DESC
        LIMIT ?
        """,
        params,
    )


def circadian_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT isodow(m.ts_local) AS dow, hour(m.ts_local) AS hour,
               count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT m.ts_local::DATE AS day, count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        WITH daily AS (
            SELECT m.ts_local::DATE AS day, count(*)::BIGINT AS messages
            {_from_join()}
            WHERE {where}
            GROUP BY 1
        ),
        ranked AS (
            SELECT day, messages,
                   day - (row_number() OVER (ORDER BY day))::INT AS grp
            FROM daily
        ),
        streaks AS (
            SELECT grp, count(*) AS streak_days, sum(messages) AS streak_messages,
                   min(day) AS streak_start
            FROM ranked GROUP BY grp
        ),
        busiest AS (SELECT day, messages FROM daily ORDER BY messages DESC LIMIT 1),
        longest AS (SELECT * FROM streaks ORDER BY streak_days DESC LIMIT 1)
        SELECT
            (SELECT streak_days FROM longest) AS longest_streak_days,
            (SELECT streak_start FROM longest) AS longest_streak_start,
            (SELECT streak_messages FROM longest) AS longest_streak_messages,
            (SELECT day FROM busiest) AS busiest_day,
            (SELECT messages FROM busiest) AS busiest_day_messages,
            (SELECT count(*) FROM daily) AS active_days
        """,
        params,
    )


# --------------------------------------------------------------------------- #
# Person spotlight


def _team(f: FilterState) -> FilterState:
    """Same window/channels/bot rules, but not narrowed to a person."""
    return replace(f, user_ids=[])


def person_scoreboard(
    conn: duckdb.DuckDBPyConnection, f: FilterState, user_id: str
) -> pd.DataFrame:
    team = _team(f)
    where, params = _where(team)
    sql = f"""
        WITH base AS (
            SELECT m.*
            {_from_join()}
            WHERE {where}
        ),
        mine AS (SELECT * FROM base WHERE user_id = ?),
        totals AS (
            SELECT count(*)::BIGINT AS team_messages,
                   count(DISTINCT user_id)::BIGINT AS team_people
            FROM base
        ),
        ranks AS (
            SELECT user_id, row_number() OVER (ORDER BY count(*) DESC) AS rank
            FROM base GROUP BY user_id
        ),
        reactions_given AS (
            SELECT count(*)::BIGINT AS n
            FROM slack.reactions r JOIN base b
              ON b.channel_id = r.channel_id AND b.ts = r.ts
            WHERE r.user_id = ?
        ),
        mentions_received AS (
            SELECT count(*)::BIGINT AS n
            FROM slack.mentions mt JOIN base b
              ON b.channel_id = mt.channel_id AND b.ts = mt.ts
            WHERE mt.mentioned_user_id = ?
        ),
        my_reply_latency AS (
            SELECT quantile_cont(
                       date_diff('second', root.ts_utc, r.ts_utc) / 60.0, 0.5
                   ) AS median_min
            FROM mine r
            JOIN slack.messages root
              ON root.channel_id = r.channel_id AND root.ts = r.thread_ts
            WHERE r.is_reply AND root.user_id IS DISTINCT FROM r.user_id
        ),
        replies_to_me AS (
            SELECT quantile_cont(
                       date_diff('second', root.ts_utc, fr.first_reply) / 60.0, 0.5
                   ) AS median_min
            FROM mine root
            JOIN (
                SELECT x.channel_id, x.thread_ts, min(x.ts_utc) AS first_reply
                FROM slack.messages x
                WHERE x.is_reply AND x.user_id IS DISTINCT FROM ?
                GROUP BY 1, 2
            ) fr ON fr.channel_id = root.channel_id AND fr.thread_ts = root.ts
            WHERE root.is_thread_root
        )
        SELECT
            any_value(mine.user_name) AS name,
            count(*)::BIGINT AS messages,
            count(*) FILTER (WHERE NOT mine.is_reply)::BIGINT AS root_posts,
            count(*) FILTER (WHERE mine.is_reply)::BIGINT AS replies,
            count(*) FILTER (WHERE mine.is_thread_root)::BIGINT AS threads_started,
            count(DISTINCT mine.channel_id)::BIGINT AS channels,
            count(DISTINCT mine.ts_local::DATE)::BIGINT AS active_days,
            min(mine.ts_utc)::DATE AS first_day,
            max(mine.ts_utc)::DATE AS last_day,
            date_diff('day', min(mine.ts_utc), max(mine.ts_utc))::INT AS tenure_days,
            sum(mine.n_reactions)::BIGINT AS reactions_received,
            (SELECT n FROM reactions_given) AS reactions_given,
            sum(mine.n_mentions)::BIGINT AS mentions_given,
            (SELECT n FROM mentions_received) AS mentions_received,
            round((SELECT median_min FROM my_reply_latency), 1)
                AS median_min_to_reply_to_others,
            round((SELECT median_min FROM replies_to_me), 1)
                AS median_min_until_others_reply,
            round(100.0 * count(*) / nullif((SELECT team_messages FROM totals), 0), 1)
                AS share_of_team_pct,
            (SELECT rank FROM ranks WHERE user_id = ?) AS rank_by_messages,
            (SELECT team_people FROM totals) AS team_people
        FROM mine
    """
    return _query_df(conn, sql, params + [user_id] * 5)


def person_monthly_activity(
    conn: duckdb.DuckDBPyConnection, f: FilterState, user_id: str
) -> pd.DataFrame:
    where, params = _where(replace(_team(f), user_ids=[user_id]))
    df = _ym(
        _query_df(
            conn,
            f"""
        SELECT m.year, m.month,
               count(*) FILTER (WHERE NOT m.is_reply)::BIGINT AS root_posts,
               count(*) FILTER (WHERE m.is_reply)::BIGINT AS replies,
               count(*)::BIGINT AS messages
        {_from_join()}
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
            params,
        )
    )
    if not df.empty:
        df["rolling_3m"] = df["messages"].rolling(3, min_periods=1).mean().round(1)
    return df


def person_share_of_team(
    conn: duckdb.DuckDBPyConnection, f: FilterState, user_id: str
) -> pd.DataFrame:
    where, params = _where(_team(f))
    return _query_df(
        conn,
        f"""
        WITH base AS (
            SELECT m.year, m.user_id
            {_from_join()}
            WHERE {where}
        ),
        per_user AS (
            SELECT year, user_id, count(*)::BIGINT AS messages,
                   row_number() OVER (PARTITION BY year ORDER BY count(*) DESC) AS rank
            FROM base GROUP BY 1, 2
        ),
        per_year AS (
            SELECT year, count(*)::BIGINT AS team_messages,
                   count(DISTINCT user_id)::BIGINT AS team_people
            FROM base GROUP BY 1
        )
        SELECT y.year, coalesce(p.messages, 0) AS messages, y.team_messages,
               y.team_people,
               round(100.0 * coalesce(p.messages, 0) / nullif(y.team_messages, 0), 1)
                   AS share_pct,
               p.rank
        FROM per_year y
        LEFT JOIN per_user p ON p.year = y.year AND p.user_id = ?
        ORDER BY y.year
        """,
        params + [user_id],
    )


def person_channel_mix(
    conn: duckdb.DuckDBPyConnection, f: FilterState, user_id: str, *, limit: int = 30
) -> pd.DataFrame:
    where, params = _where(_team(f))
    params.extend([user_id, limit])
    return _query_df(
        conn,
        f"""
        WITH base AS (
            SELECT m.channel_id, c.name AS channel_name, m.user_id
            {_from_join()}
            WHERE {where}
        ),
        per_channel AS (
            SELECT channel_id, channel_name,
                   count(*)::BIGINT AS channel_messages,
                   count(*) FILTER (WHERE user_id = ?)::BIGINT AS messages
            FROM base GROUP BY 1, 2
        )
        SELECT channel_name, messages, channel_messages,
               round(100.0 * messages / nullif(channel_messages, 0), 1) AS share_pct
        FROM per_channel
        WHERE messages > 0
        ORDER BY messages DESC
        LIMIT ?
        """,
        params,
    )


def person_circadian(
    conn: duckdb.DuckDBPyConnection, f: FilterState, user_id: str
) -> pd.DataFrame:
    """dow × hour for the person and for the team, each as % of own total."""
    where, params = _where(_team(f))
    return _query_df(
        conn,
        f"""
        WITH base AS (
            SELECT isodow(m.ts_local) AS dow, hour(m.ts_local) AS hour,
                   m.user_id = ? AS is_person
            {_from_join()}
            WHERE {where}
        ),
        counts AS (
            SELECT CASE WHEN is_person THEN 'person' ELSE 'team' END AS who,
                   dow, hour, count(*)::BIGINT AS messages
            FROM base GROUP BY 1, 2, 3
        )
        SELECT who, dow, hour, messages,
               round(100.0 * messages / sum(messages) OVER (PARTITION BY who), 2)
                   AS pct
        FROM counts
        ORDER BY who, dow, hour
        """,
        [user_id] + params,
    )


def person_calendar_daily(
    conn: duckdb.DuckDBPyConnection, f: FilterState, user_id: str
) -> pd.DataFrame:
    return calendar_daily(conn, replace(_team(f), user_ids=[user_id]))


def person_collaborators(
    conn: duckdb.DuckDBPyConnection, f: FilterState, user_id: str, *, limit: int = 15
) -> pd.DataFrame:
    """Long format: other_name, kind, n — top ``limit`` others by total strength."""
    where, params = _where(_team(f))
    sql = f"""
        WITH base AS (
            SELECT m.channel_id, m.ts, m.user_id, m.is_reply, m.parent_user_id
            {_from_join()}
            WHERE {where}
        ),
        pairs AS (
            SELECT parent_user_id AS other, 'replied in their thread' AS kind,
                   count(*)::BIGINT AS n
            FROM base WHERE user_id = ? AND is_reply
              AND parent_user_id IS NOT NULL AND parent_user_id <> ?
            GROUP BY 1
            UNION ALL
            SELECT user_id, 'they replied in my thread', count(*)::BIGINT
            FROM base WHERE parent_user_id = ? AND is_reply AND user_id <> ?
            GROUP BY 1
            UNION ALL
            SELECT mt.mentioned_user_id, 'I mentioned them', count(*)::BIGINT
            FROM slack.mentions mt JOIN base b
              ON b.channel_id = mt.channel_id AND b.ts = mt.ts
            WHERE b.user_id = ? AND mt.mentioned_user_id <> ?
            GROUP BY 1
            UNION ALL
            SELECT b.user_id, 'they mentioned me', count(*)::BIGINT
            FROM slack.mentions mt JOIN base b
              ON b.channel_id = mt.channel_id AND b.ts = mt.ts
            WHERE mt.mentioned_user_id = ? AND b.user_id <> ?
            GROUP BY 1
            UNION ALL
            SELECT b.user_id, 'I reacted to them', count(*)::BIGINT
            FROM slack.reactions r JOIN base b
              ON b.channel_id = r.channel_id AND b.ts = r.ts
            WHERE r.user_id = ? AND b.user_id <> ?
            GROUP BY 1
            UNION ALL
            SELECT r.user_id, 'they reacted to me', count(*)::BIGINT
            FROM slack.reactions r JOIN base b
              ON b.channel_id = r.channel_id AND b.ts = r.ts
            WHERE b.user_id = ? AND r.user_id IS NOT NULL AND r.user_id <> ?
            GROUP BY 1
        ),
        totals AS (
            SELECT other, sum(n) AS strength FROM pairs GROUP BY 1
            ORDER BY strength DESC LIMIT ?
        )
        SELECT
            coalesce(u.real_name, u.display_name, u.handle, p.other) AS other_name,
            p.kind, p.n, t.strength
        FROM pairs p
        JOIN totals t USING (other)
        LEFT JOIN slack.users u ON u.user_id = p.other
        ORDER BY t.strength DESC, other_name, p.kind
    """
    return _query_df(conn, sql, params + [user_id] * 12 + [limit])


def person_reaction_profile(
    conn: duckdb.DuckDBPyConnection, f: FilterState, user_id: str, *, limit: int = 12
) -> pd.DataFrame:
    """emoji, direction ('given' | 'received'), n."""
    where, params = _where(_team(f))
    sql = f"""
        WITH base AS (
            SELECT m.channel_id, m.ts, m.user_id
            {_from_join()}
            WHERE {where}
        ),
        given AS (
            SELECT r.emoji, 'given' AS direction, count(*)::BIGINT AS n
            FROM slack.reactions r JOIN base b
              ON b.channel_id = r.channel_id AND b.ts = r.ts
            WHERE r.user_id = ?
            GROUP BY 1 ORDER BY n DESC LIMIT ?
        ),
        received AS (
            SELECT r.emoji, 'received' AS direction, count(*)::BIGINT AS n
            FROM slack.reactions r JOIN base b
              ON b.channel_id = r.channel_id AND b.ts = r.ts
            WHERE b.user_id = ?
            GROUP BY 1 ORDER BY n DESC LIMIT ?
        )
        SELECT * FROM given UNION ALL SELECT * FROM received
    """
    return _query_df(conn, sql, params + [user_id, limit, user_id, limit])


def person_text_profile(
    conn: duckdb.DuckDBPyConnection, f: FilterState, user_id: str
) -> pd.DataFrame:
    where, params = _where(_team(f))
    return _query_df(
        conn,
        f"""
        SELECT
            CASE WHEN m.user_id = ? THEN 'person' ELSE 'team' END AS who,
            count(*)::BIGINT AS messages,
            round(avg(m.text_len), 0) AS avg_text_len,
            round(quantile_cont(m.text_len, 0.5), 0) AS median_text_len,
            round(100.0 * avg(CASE WHEN m.has_link THEN 1.0 ELSE 0.0 END), 1)
                AS link_pct,
            round(100.0 * avg(CASE WHEN m.n_files > 0 THEN 1.0 ELSE 0.0 END), 1)
                AS file_pct,
            round(100.0 * avg(CASE WHEN m.is_reply THEN 1.0 ELSE 0.0 END), 1)
                AS reply_pct,
            round(100.0 * avg(CASE WHEN m.edited THEN 1.0 ELSE 0.0 END), 1)
                AS edited_pct,
            round(100.0 * avg(CASE WHEN m.n_mentions > 0 THEN 1.0 ELSE 0.0 END), 1)
                AS mentions_pct,
            round(avg(m.n_reactions), 2) AS avg_reactions_received
        {_from_join()}
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        [user_id] + params,
    )


def person_top_messages(
    conn: duckdb.DuckDBPyConnection, f: FilterState, user_id: str, *, limit: int = 10
) -> pd.DataFrame:
    where, params = _where(replace(_team(f), user_ids=[user_id]))
    params.append(limit)
    return _query_df(
        conn,
        f"""
        SELECT m.ts_local::DATE AS day, c.name AS channel_name,
               m.n_reactions, m.reply_count, left(m.text, 160) AS text
        {_from_join()}
        WHERE {where} AND (m.n_reactions > 0 OR m.reply_count > 0)
        ORDER BY (m.n_reactions + m.reply_count) DESC, m.ts_utc DESC
        LIMIT ?
        """,
        params,
    )


def person_streaks(
    conn: duckdb.DuckDBPyConnection, f: FilterState, user_id: str
) -> pd.DataFrame:
    return streak_stats(conn, replace(_team(f), user_ids=[user_id]))
