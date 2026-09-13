"""Person-spotlight Slack queries."""

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
from data_dumps.slack_queries.workspace import calendar_daily, streak_stats


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
