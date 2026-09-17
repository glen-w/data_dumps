"""Filter state and DuckDB queries for the Ring explorer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        return chips


def _where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    p = f"{alias}." if alias else ""
    if f.year_start is not None:
        clauses.append(f"{p}year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{p}year <= ?")
        params.append(f.year_end)
    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT, max(year)::INT,
            min(local_date)::DATE, max(local_date)::DATE
        FROM (
            SELECT year, local_date FROM ring.device_events
            UNION ALL
            SELECT year, local_date FROM ring.events
            UNION ALL
            SELECT year, local_date FROM ring.app_events
        )
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2024, 2026
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
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


def previous_window(f: FilterState) -> FilterState | None:
    bounds = query_util.previous_year_bounds(f.year_start, f.year_end)
    if bounds is None:
        return None
    return FilterState(year_start=bounds[0], year_end=bounds[1])


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    de_where, de_params = _where("de", f)
    ev_where, ev_params = _where("e", f)
    app_where, app_params = _where("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            (SELECT count(*)::BIGINT FROM ring.devices) AS devices,
            (
                SELECT count(*)::BIGINT FROM ring.device_events de
                WHERE {de_where}
            ) AS device_events,
            (
                SELECT count(*)::BIGINT FROM ring.device_events de
                WHERE {de_where} AND de.message_type = 'device_offline'
            ) AS offline_flips,
            (
                SELECT count(*)::BIGINT FROM ring.device_events de
                WHERE {de_where} AND de.message_type = 'device_online'
            ) AS online_flips,
            (
                SELECT count(*)::BIGINT FROM ring.events e
                WHERE {ev_where}
            ) AS motion_events,
            (
                SELECT count(*)::BIGINT FROM ring.app_events a
                WHERE {app_where}
            ) AS app_events,
            (
                SELECT count(*)::BIGINT FROM ring.app_events a
                WHERE {app_where} AND a.event = 'App Launched'
            ) AS app_launches,
            (
                SELECT count(*)::BIGINT
                FROM ring.subscriptions
                WHERE lower(coalesce(status, '')) = 'active'
            ) AS active_plans,
            (
                SELECT coalesce(sum(bytes), 0)::BIGINT
                FROM ring.dump_inventory
            ) AS footprint_bytes
        """,
        de_params + de_params + de_params + ev_params + app_params + app_params,
    )


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
    bounds = data_bounds(conn)
    if prev_f.year_start is None or prev_f.year_start < bounds["min_year"]:
        current["compare_note"] = (
            f"previous window ({prev_f.year_start}–{prev_f.year_end}) "
            f"predates data (min year {bounds['min_year']})"
        )
        return current
    prev = _scoreboard_row(conn, prev_f)
    prev["window"] = f"previous ({prev_f.year_start}–{prev_f.year_end})"
    return pd.concat([current, prev], ignore_index=True)


def daily_offline_flips(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("de", f)
    return _query_df(
        conn,
        f"""
        SELECT
            local_date AS day,
            count(*) FILTER (WHERE message_type = 'device_offline')::BIGINT AS offline,
            count(*) FILTER (WHERE message_type = 'device_online')::BIGINT AS online,
            count(*)::BIGINT AS flips
        FROM ring.device_events de
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def device_state_timeline(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("de", f)
    return _query_df(
        conn,
        f"""
        SELECT
            ts_local,
            local_date AS day,
            message_type,
            category
        FROM ring.device_events de
        WHERE {where}
        ORDER BY ts_local
        """,
        params,
    )


def offline_stretches(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 15,
) -> pd.DataFrame:
    """Longest offline stretches inferred from consecutive offline→online pairs."""
    where, params = _where("de", f)
    return _query_df(
        conn,
        f"""
        WITH ordered AS (
            SELECT
                ts_utc,
                ts_local,
                message_type,
                lead(ts_utc) OVER (ORDER BY ts_utc) AS next_ts_utc,
                lead(message_type) OVER (ORDER BY ts_utc) AS next_type
            FROM ring.device_events de
            WHERE {where}
        )
        SELECT
            ts_local AS offline_at,
            next_ts_utc AS online_at_utc,
            date_diff('minute', ts_utc, next_ts_utc) AS minutes_offline
        FROM ordered
        WHERE message_type = 'device_offline'
          AND next_type = 'device_online'
          AND next_ts_utc IS NOT NULL
        ORDER BY minutes_offline DESC NULLS LAST
        LIMIT ?
        """,
        params + [limit],
    )


def motion_timeline(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("e", f)
    return _query_df(
        conn,
        f"""
        SELECT
            ts_local,
            local_date AS day,
            event_type,
            detection_type,
            duration_seconds,
            status
        FROM ring.events e
        WHERE {where}
        ORDER BY ts_local
        """,
        params,
    )


def motion_duration_outliers(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("e", f)
    return _query_df(
        conn,
        f"""
        SELECT
            ts_local,
            duration_seconds,
            event_type,
            detection_type,
            status
        FROM ring.events e
        WHERE {where} AND duration_seconds IS NOT NULL
        ORDER BY duration_seconds DESC
        """,
        params,
    )


def app_daily_volume(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            local_date AS day,
            count(*)::BIGINT AS events,
            count(*) FILTER (WHERE event = 'App Launched')::BIGINT AS launches,
            count(*) FILTER (
                WHERE event ILIKE '%PushNotification%'
                   OR event ILIKE '%Rich Notification%'
            )::BIGINT AS notifications
        FROM ring.app_events a
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def app_top_events(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 20,
) -> pd.DataFrame:
    where, params = _where("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            coalesce(event, '(none)') AS event,
            count(*)::BIGINT AS events
        FROM ring.app_events a
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
        LIMIT ?
        """,
        params + [limit],
    )


def app_busiest_days(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    limit: int = 10,
) -> pd.DataFrame:
    where, params = _where("a", f)
    return _query_df(
        conn,
        f"""
        SELECT
            local_date AS day,
            count(*)::BIGINT AS events,
            count(DISTINCT event)::BIGINT AS event_types
        FROM ring.app_events a
        WHERE {where}
        GROUP BY 1
        ORDER BY events DESC
        LIMIT ?
        """,
        params + [limit],
    )


def subscription_ledger(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            plan_id,
            status,
            quantity,
            cancel_at_period_end,
            created_at,
            current_period_start,
            current_period_end,
            start_at
        FROM ring.subscriptions
        ORDER BY created_at
        """,
    )


def accounting_ledger(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            entry_type,
            amount,
            currency_code,
            status,
            invoice_number,
            payment_provider,
            description,
            created_at,
            period_start,
            period_end
        FROM ring.accounting
        ORDER BY created_at
        """,
    )


def inventory_summary(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            kind,
            count(*)::BIGINT AS files,
            coalesce(sum(bytes), 0)::BIGINT AS bytes,
            coalesce(sum(row_count), 0)::BIGINT AS rows
        FROM ring.dump_inventory
        GROUP BY 1
        ORDER BY bytes DESC
        """,
    )


def devices_table(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _query_df(
        conn,
        """
        SELECT
            device_name,
            device_id,
            created_at,
            timezone,
            video_storage_enabled,
            people_detection_eligible,
            continuous_video_recording_subscribed
        FROM ring.devices
        ORDER BY created_at
        """,
    )


def _events_union_where(f: FilterState) -> tuple[str, list[Any]]:
    """Year filter for the union of Ring event tables (no table alias)."""
    return _where("", f)


def calendar_daily_events(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    """Daily count of device + motion + app events (activity volume)."""
    where, params = _events_union_where(f)
    return _query_df(
        conn,
        f"""
        SELECT local_date AS day, count(*)::BIGINT AS events
        FROM (
            SELECT local_date, year FROM ring.device_events
            UNION ALL
            SELECT local_date, year FROM ring.events
            UNION ALL
            SELECT local_date, year FROM ring.app_events
        ) u
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def monthly_events(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Monthly count of device + motion + app events."""
    where, params = _events_union_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            date_trunc('month', local_date)::DATE AS month,
            count(*)::BIGINT AS events
        FROM (
            SELECT local_date, year FROM ring.device_events
            UNION ALL
            SELECT local_date, year FROM ring.events
            UNION ALL
            SELECT local_date, year FROM ring.app_events
        ) u
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def monthly_motion_events(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("", f)
    return _query_df(
        conn,
        f"""
        SELECT
            date_trunc('month', local_date)::DATE AS month,
            count(*)::BIGINT AS events
        FROM ring.events
        WHERE {where} AND local_date IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def calendar_daily_motion(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("", f)
    return _query_df(
        conn,
        f"""
        SELECT local_date AS day, count(*)::BIGINT AS events
        FROM ring.events
        WHERE {where} AND local_date IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def monthly_app_events(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where("", f)
    return _query_df(
        conn,
        f"""
        SELECT
            date_trunc('month', local_date)::DATE AS month,
            count(*)::BIGINT AS events
        FROM ring.app_events
        WHERE {where} AND local_date IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def calendar_daily_app_events(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _where("", f)
    return _query_df(
        conn,
        f"""
        SELECT local_date AS day, count(*)::BIGINT AS events
        FROM ring.app_events
        WHERE {where} AND local_date IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )
