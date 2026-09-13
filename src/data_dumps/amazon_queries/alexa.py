"""Amazon Alexa analytics queries."""

from __future__ import annotations

import duckdb
import pandas as pd

from data_dumps.amazon_queries.filters import FilterState, _query_df, _year_clause


def alexa_scoreboard(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS utterances,
            count(DISTINCT utterance_tag)::BIGINT AS tags,
            min(intent_ts_local)::TIMESTAMP AS first_ts,
            max(intent_ts_local)::TIMESTAMP AS last_ts
        FROM amazon.alexa_intents a
        WHERE {where}
        """,
        params,
    )


def alexa_tags(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT utterance_tag AS tag, count(*)::BIGINT AS n
        FROM amazon.alexa_intents a
        WHERE {where}
        GROUP BY 1
        ORDER BY n DESC
        """,
        params,
    )


def alexa_circadian(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT dow, hour, count(*)::BIGINT AS events
        FROM amazon.alexa_intents a
        WHERE {where} AND dow IS NOT NULL AND hour IS NOT NULL
        GROUP BY 1, 2
        """,
        params,
    )


def alexa_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            count(*)::BIGINT AS utterances
        FROM amazon.alexa_intents a
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def alexa_devices(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("s", f)
    return _query_df(
        conn,
        f"""
        SELECT coalesce(device_type, 'unknown') AS device_type, count(*)::BIGINT AS events
        FROM amazon.alexa_sessions s
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
        """,
        params,
    )


def alexa_show_engagement(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _year_clause("s", f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            sum(voice_count)::BIGINT AS voice,
            sum(touch_count)::BIGINT AS touch,
            sum(impression_count)::BIGINT AS impressions
        FROM amazon.alexa_show_daily s
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def alexa_skills(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT skill_name, stage, status, enabled_ts_utc
        FROM amazon.alexa_skills
        ORDER BY enabled_ts_utc DESC NULLS LAST
        LIMIT 50
        """,
    )


def alexa_tag_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            make_date(year::INT, month::INT, 1) AS month_start,
            utterance_tag AS tag,
            count(*)::BIGINT AS n
        FROM amazon.alexa_intents a
        WHERE {where} AND year IS NOT NULL AND month IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def alexa_top_utterances(
    conn: duckdb.DuckDBPyConnection, f: FilterState, limit: int = 25
) -> pd.DataFrame:
    where, params = _year_clause("a", f)
    return _query_df(
        conn,
        f"""
        SELECT utterance, utterance_tag AS tag, count(*)::BIGINT AS n
        FROM amazon.alexa_intents a
        WHERE {where} AND utterance IS NOT NULL AND length(utterance) > 2
        GROUP BY 1, 2
        ORDER BY n DESC
        LIMIT ?
        """,
        params + [limit],
    )
