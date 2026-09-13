"""Workspace-level Slack queries."""

from __future__ import annotations

from dataclasses import replace

import duckdb
import pandas as pd

from data_dumps.slack_queries.filters import (
    FilterState,
    _from_join,
    _query_df,
    _where,
    _ym,
)


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
        _reply_latency_cte(where) + """
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
        _reply_latency_cte(where) + """
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
