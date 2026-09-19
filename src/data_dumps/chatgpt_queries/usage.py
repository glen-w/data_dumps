"""ChatGPT queries — usage."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util
from data_dumps.chatgpt_queries.filters import (
    FilterState,
    _conv_where,
    _msg_where,
    _query_df,
    has_table,
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
    min_row = conn.execute(
        "SELECT min(year)::INT FROM chatgpt.messages WHERE year IS NOT NULL"
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
        roles=list(f.roles),
        model_families=list(f.model_families),
        content_types=list(f.content_types),
        title_search=f.title_search,
        conversation_id=f.conversation_id,
        shared_only=f.shared_only,
    )
    prev = _scoreboard_row(conn, prev_f)
    current["window"] = "current"
    prev["window"] = f"previous ({prev_start}–{prev_end})"
    return pd.concat([current, prev], ignore_index=True)


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    mw, mp = _msg_where(f)
    cw, cp = _conv_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            (SELECT count(*)::BIGINT FROM chatgpt.messages m WHERE {mw}) AS messages,
            (SELECT count(DISTINCT m.conversation_id)::BIGINT
             FROM chatgpt.messages m WHERE {mw}) AS conversations,
            (SELECT count(DISTINCT m.ts_local::DATE)::BIGINT
             FROM chatgpt.messages m WHERE {mw}) AS active_days,
            (SELECT count(*)::BIGINT FROM chatgpt.messages m
             WHERE {mw} AND m.role = 'user') AS user_messages,
            (SELECT count(*)::BIGINT FROM chatgpt.messages m
             WHERE {mw} AND m.role = 'assistant') AS assistant_messages,
            (SELECT coalesce(sum(m.char_count), 0)::BIGINT FROM chatgpt.messages m
             WHERE {mw} AND m.role = 'user') AS user_chars,
            (SELECT coalesce(sum(m.char_count), 0)::BIGINT FROM chatgpt.messages m
             WHERE {mw} AND m.role = 'assistant') AS assistant_chars,
            (SELECT count(*)::BIGINT FROM chatgpt.messages m
             WHERE {mw} AND m.content_type = 'thoughts') AS thought_messages,
            (SELECT coalesce(sum(m.image_count), 0)::BIGINT FROM chatgpt.messages m
             WHERE {mw}) AS images,
            (SELECT count(*)::BIGINT FROM chatgpt.conversations c
             WHERE {cw} AND c.is_shared) AS shared_conversations,
            (SELECT min(m.ts_local)::DATE FROM chatgpt.messages m WHERE {mw}) AS first_day,
            (SELECT max(m.ts_local)::DATE FROM chatgpt.messages m WHERE {mw}) AS last_day
        """,
        [*mp, *mp, *mp, *mp, *mp, *mp, *mp, *mp, *mp, *cp, *mp, *mp],
    )


def streak_stats(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH daily AS (
            SELECT m.ts_local::DATE AS day, count(*)::BIGINT AS messages
            FROM chatgpt.messages m
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
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS messages,
            count(*) FILTER (WHERE role = 'user')::BIGINT AS user_messages,
            count(*) FILTER (WHERE role = 'assistant')::BIGINT AS assistant_messages,
            count(DISTINCT conversation_id)::BIGINT AS conversations,
            coalesce(sum(char_count) FILTER (WHERE role = 'user'), 0)::BIGINT AS user_chars
        FROM chatgpt.messages m
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
        SELECT m.ts_local::DATE AS day, count(*)::BIGINT AS messages
        FROM chatgpt.messages m
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


def conversations_monthly_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _conv_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*)::BIGINT AS conversations
        FROM chatgpt.conversations c
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def conversations_daily_total(
    conn: duckdb.DuckDBPyConnection, year_start: int | None, year_end: int | None
) -> pd.DataFrame:
    f = FilterState(year_start=year_start, year_end=year_end)
    where, params = _conv_where(f)
    return _query_df(
        conn,
        f"""
        SELECT c.create_ts_local::DATE AS day, count(*)::BIGINT AS conversations
        FROM chatgpt.conversations c
        WHERE {where} AND c.create_ts_local IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def conversation_messages_monthly(
    conn: duckdb.DuckDBPyConnection,
    year_start: int | None,
    year_end: int | None,
    conversation_id: str,
) -> pd.DataFrame:
    f = FilterState(
        year_start=year_start,
        year_end=year_end,
        conversation_id=conversation_id,
    )
    return messages_monthly(conn, f)[["year_month", "messages"]]


def conversation_options(
    conn: duckdb.DuckDBPyConnection, *, limit: int = 40
) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT conversation_id, coalesce(nullif(title, ''), conversation_id) AS label,
               n_messages
        FROM chatgpt.conversations
        ORDER BY n_messages DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [
        {"value": str(r[0]), "label": f"{r[1][:60]} ({r[2]})"} for r in rows if r[0]
    ]


def model_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(model_family, 'unknown') AS model_family,
            coalesce(model_slug, 'unknown') AS model_slug,
            count(*)::BIGINT AS messages
        FROM chatgpt.messages m
        WHERE {where} AND role = 'assistant'
        GROUP BY 1, 2
        ORDER BY messages DESC
        """,
        params,
    )


def model_family_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            coalesce(model_family, 'unknown') AS model_family,
            count(*)::BIGINT AS messages
        FROM chatgpt.messages m
        WHERE {where} AND role = 'assistant' AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 3 DESC
        """,
        params,
    )


def content_type_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT content_type, count(*)::BIGINT AS messages
        FROM chatgpt.messages m
        WHERE {where}
        GROUP BY 1
        ORDER BY messages DESC
        """,
        params,
    )


def role_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT role, count(*)::BIGINT AS messages,
               coalesce(sum(char_count), 0)::BIGINT AS chars
        FROM chatgpt.messages m
        WHERE {where}
        GROUP BY 1
        ORDER BY messages DESC
        """,
        params,
    )


def weekday_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT weekday::INT AS dow, hour, count(*)::BIGINT AS messages
        FROM chatgpt.messages m
        WHERE {where} AND weekday IS NOT NULL AND hour IS NOT NULL
        GROUP BY 1, 2
        """,
        params,
    )


def calendar_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            m.ts_local::DATE AS day,
            isodow(m.ts_local) AS weekday,
            weekofyear(m.ts_local) AS iso_week,
            year(m.ts_local) AS year,
            count(*)::BIGINT AS events
        FROM chatgpt.messages m
        WHERE {where}
        GROUP BY 1, 2, 3, 4
        ORDER BY 1
        """,
        params,
    )


def top_conversations(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    mw, mp = _msg_where(f, "m")
    return _query_df(
        conn,
        f"""
        SELECT
            c.conversation_id,
            coalesce(nullif(c.title, ''), '(untitled)') AS title,
            count(*)::BIGINT AS messages,
            count(*) FILTER (WHERE m.role = 'user')::BIGINT AS user_messages,
            coalesce(sum(m.char_count) FILTER (WHERE m.role = 'user'), 0)::BIGINT
                AS user_chars,
            min(m.ts_local)::DATE AS first_day,
            max(m.ts_local)::DATE AS last_day,
            c.default_model_family,
            c.is_shared,
            c.gizmo_id IS NOT NULL AS is_project
        FROM chatgpt.messages m
        JOIN chatgpt.conversations c ON c.conversation_id = m.conversation_id
        WHERE {mw}
        GROUP BY
            c.conversation_id, c.title, c.default_model_family, c.is_shared, c.gizmo_id
        ORDER BY messages DESC
        LIMIT ?
        """,
        [*mp, limit],
    )


def conversation_scatter(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 400
) -> pd.DataFrame:
    cw, cp = _conv_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            conversation_id,
            coalesce(nullif(title, ''), '(untitled)') AS title,
            n_messages,
            n_user,
            user_chars,
            assistant_chars,
            n_thoughts,
            n_images,
            default_model_family,
            is_shared,
            date_diff('day', create_ts_local, update_ts_local) AS span_days,
            create_ts_local::DATE AS created
        FROM chatgpt.conversations c
        WHERE {cw}
          AND n_messages > 0
          AND create_ts_local IS NOT NULL
          AND update_ts_local IS NOT NULL
        ORDER BY n_messages DESC
        LIMIT ?
        """,
        [*cp, limit],
    )


def forgotten_conversations(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    """Deep threads silent for ≥2 years relative to the filter end."""
    max_row = conn.execute("SELECT max(year) FROM chatgpt.messages").fetchone()
    end_year: int | None = f.year_end
    if end_year is None and max_row is not None:
        end_year = max_row[0]
    if end_year is None:
        return pd.DataFrame()
    cutoff_year = int(end_year) - 2
    mw, mp = _msg_where(
        FilterState(
            year_start=None,
            year_end=None,
            roles=list(f.roles),
            model_families=[],
            content_types=list(f.content_types),
            title_search=f.title_search,
            conversation_id=f.conversation_id,
            shared_only=f.shared_only,
        )
    )
    return _query_df(
        conn,
        f"""
        WITH activity AS (
            SELECT
                m.conversation_id,
                count(*)::BIGINT AS messages,
                max(m.ts_local) AS last_ts,
                min(m.ts_local) AS first_ts
            FROM chatgpt.messages m
            WHERE {mw}
            GROUP BY 1
        )
        SELECT
            c.conversation_id,
            coalesce(nullif(c.title, ''), '(untitled)') AS title,
            a.messages,
            a.first_ts::DATE AS first_day,
            a.last_ts::DATE AS last_day,
            date_diff('day', a.last_ts, current_date) AS days_silent
        FROM activity a
        JOIN chatgpt.conversations c ON c.conversation_id = a.conversation_id
        WHERE year(a.last_ts) <= ?
          AND a.messages >= 6
        ORDER BY a.messages DESC, a.last_ts
        LIMIT ?
        """,
        [*mp, cutoff_year, limit],
    )


def comeback_conversations(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    """Threads resumed after a ≥90 day silence, within the filter years."""
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH ordered AS (
            SELECT
                conversation_id,
                ts_local,
                lag(ts_local) OVER (
                    PARTITION BY conversation_id ORDER BY ts_local
                ) AS prev_ts
            FROM chatgpt.messages m
            WHERE {where}
        ),
        gaps AS (
            SELECT
                conversation_id,
                prev_ts,
                ts_local,
                date_diff('day', prev_ts, ts_local) AS gap_days
            FROM ordered
            WHERE prev_ts IS NOT NULL
              AND date_diff('day', prev_ts, ts_local) >= 90
        )
        SELECT
            c.conversation_id,
            coalesce(nullif(c.title, ''), '(untitled)') AS title,
            g.gap_days,
            g.prev_ts::DATE AS paused_on,
            g.ts_local::DATE AS resumed_on,
            c.n_messages
        FROM gaps g
        JOIN chatgpt.conversations c ON c.conversation_id = g.conversation_id
        ORDER BY g.gap_days DESC, g.ts_local DESC
        LIMIT ?
        """,
        [*params, limit],
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
            FROM chatgpt.messages m
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


def reply_latency(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """User → next assistant latency distribution (minutes)."""
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH ordered AS (
            SELECT
                conversation_id,
                role,
                ts_local,
                lead(role) OVER (
                    PARTITION BY conversation_id ORDER BY ts_local, message_id
                ) AS next_role,
                lead(ts_local) OVER (
                    PARTITION BY conversation_id ORDER BY ts_local, message_id
                ) AS next_ts
            FROM chatgpt.messages m
            WHERE {where}
              AND role IN ('user', 'assistant')
              AND content_type IN ('text', 'multimodal_text')
        )
        SELECT
            count(*)::BIGINT AS pairs,
            round(avg(epoch(next_ts - ts_local) / 60.0), 2) AS mean_minutes,
            round(median(epoch(next_ts - ts_local) / 60.0), 2) AS median_minutes,
            round(quantile_cont(epoch(next_ts - ts_local) / 60.0, 0.9), 2)
                AS p90_minutes
        FROM ordered
        WHERE role = 'user' AND next_role = 'assistant' AND next_ts IS NOT NULL
          AND epoch(next_ts - ts_local) BETWEEN 0 AND 86400 * 2
        """,
        params,
    )


def reply_latency_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        WITH ordered AS (
            SELECT
                conversation_id,
                role,
                ts_local,
                year,
                month,
                lead(role) OVER (
                    PARTITION BY conversation_id ORDER BY ts_local, message_id
                ) AS next_role,
                lead(ts_local) OVER (
                    PARTITION BY conversation_id ORDER BY ts_local, message_id
                ) AS next_ts
            FROM chatgpt.messages m
            WHERE {where}
              AND role IN ('user', 'assistant')
              AND content_type IN ('text', 'multimodal_text')
        )
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            round(median(epoch(next_ts - ts_local) / 60.0), 2) AS median_minutes,
            count(*)::BIGINT AS pairs
        FROM ordered
        WHERE role = 'user' AND next_role = 'assistant' AND next_ts IS NOT NULL
          AND year IS NOT NULL AND month IS NOT NULL
          AND epoch(next_ts - ts_local) BETWEEN 0 AND 86400 * 2
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def gizmo_usage(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 20
) -> pd.DataFrame:
    cw, cp = _conv_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            gizmo_id,
            count(*)::BIGINT AS conversations,
            sum(n_messages)::BIGINT AS messages,
            sum(user_chars)::BIGINT AS user_chars
        FROM chatgpt.conversations c
        WHERE {cw} AND gizmo_id IS NOT NULL
        GROUP BY 1
        ORDER BY conversations DESC
        LIMIT ?
        """,
        [*cp, limit],
    )


def modality_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            count(*) FILTER (WHERE content_type = 'thoughts')::BIGINT AS thoughts,
            coalesce(sum(image_count), 0)::BIGINT AS images,
            coalesce(sum(char_count) FILTER (WHERE role = 'assistant'), 0)::BIGINT
                AS assistant_chars,
            coalesce(sum(char_count) FILTER (WHERE role = 'user'), 0)::BIGINT
                AS user_chars
        FROM chatgpt.messages m
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def content_type_monthly(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year, month) AS year_month,
            coalesce(content_type, 'unknown') AS content_type,
            count(*)::BIGINT AS messages
        FROM chatgpt.messages m
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, messages DESC
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
            FROM chatgpt.messages m
            WHERE {where} AND role = 'user'
        )
        SELECT bucket, count(*)::BIGINT AS messages
        FROM tagged
        GROUP BY bucket, ord
        ORDER BY ord
        """,
        params,
    )


def conversation_depth(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _conv_where(f)
    return _query_df(
        conn,
        f"""
        WITH tagged AS (
            SELECT
                CASE
                    WHEN coalesce(n_messages, 0) <= 2 THEN 1
                    WHEN n_messages <= 10 THEN 2
                    WHEN n_messages <= 40 THEN 3
                    ELSE 4
                END AS ord,
                CASE
                    WHEN coalesce(n_messages, 0) <= 2 THEN '1–2'
                    WHEN n_messages <= 10 THEN '3–10'
                    WHEN n_messages <= 40 THEN '11–40'
                    ELSE '41+'
                END AS bucket
            FROM chatgpt.conversations c
            WHERE {where}
        )
        SELECT bucket, count(*)::BIGINT AS conversations
        FROM tagged
        GROUP BY bucket, ord
        ORDER BY ord
        """,
        params,
    )


def conversation_flags(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _conv_where(f)
    return _query_df(
        conn,
        f"""
        WITH base AS (
            SELECT
                count(*) FILTER (WHERE coalesce(is_archived, false))::BIGINT AS archived,
                count(*) FILTER (WHERE coalesce(is_starred, false))::BIGINT AS starred,
                count(*) FILTER (WHERE coalesce(is_study_mode, false))::BIGINT
                    AS study_mode,
                count(*) FILTER (WHERE coalesce(is_do_not_remember, false))::BIGINT
                    AS do_not_remember
            FROM chatgpt.conversations c
            WHERE {where}
        )
        SELECT 'archived' AS flag, archived AS conversations FROM base
        UNION ALL
        SELECT 'starred', starred FROM base
        UNION ALL
        SELECT 'study_mode', study_mode FROM base
        UNION ALL
        SELECT 'do_not_remember', do_not_remember FROM base
        """,
        params,
    )


def assets_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    if not has_table(conn, "assets"):
        return pd.DataFrame()
    clauses = ["year IS NOT NULL", "month IS NOT NULL"]
    params: list[Any] = []
    query_util.append_year_clause(clauses, params, "", f.year_start, f.year_end)
    where = " AND ".join(clauses)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', year::INT, month::INT) AS year_month,
            count(*)::BIGINT AS files,
            coalesce(sum(file_size_bytes), 0)::BIGINT AS bytes
        FROM chatgpt.assets
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def asset_extension_mix(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    if not has_table(conn, "assets"):
        return pd.DataFrame()
    return _query_df(
        conn,
        """
        SELECT
            coalesce(file_extension, 'unknown') AS file_extension,
            source,
            count(*)::BIGINT AS files,
            coalesce(sum(file_size_bytes), 0)::BIGINT AS bytes
        FROM chatgpt.assets
        GROUP BY 1, 2
        ORDER BY files DESC
        """,
    )


def shared_list(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 40
) -> pd.DataFrame:
    cw, cp = _conv_where(f, alias="c2")
    return _query_df(
        conn,
        f"""
        SELECT
            s.title,
            s.conversation_id,
            s.is_anonymous,
            c.n_messages,
            c.default_model_family,
            c.create_ts_local::DATE AS created
        FROM chatgpt.shared s
        LEFT JOIN chatgpt.conversations c ON c.conversation_id = s.conversation_id
        WHERE s.conversation_id IS NULL OR exists (
            SELECT 1 FROM chatgpt.conversations c2
            WHERE c2.conversation_id = s.conversation_id AND ({cw})
        )
        ORDER BY c.n_messages DESC NULLS LAST
        LIMIT ?
        """,
        [*cp, limit],
    )


def conversation_messages(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 80
) -> pd.DataFrame:
    if not f.conversation_id:
        return pd.DataFrame()
    where, params = _msg_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            ts_local,
            role,
            content_type,
            model_slug,
            char_count,
            image_count,
            left(coalesce(text, ''), 240) AS preview
        FROM chatgpt.messages m
        WHERE {where}
        ORDER BY ts_local, message_id
        LIMIT ?
        """,
        [*params, limit],
    )
