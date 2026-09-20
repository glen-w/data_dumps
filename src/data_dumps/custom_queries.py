"""Filter state and DuckDB queries for user manifest sources (``custom.*``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util


@dataclass
class FilterState:
    source_slug: str | None = None
    source_label: str | None = None
    year_start: int | None = None
    year_end: int | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.source_label:
            chips.append(("source", self.source_label))
        chip = query_util.year_chip(self.year_start, self.year_end)
        if chip is not None:
            chips.append(chip)
        return chips


def _where(f: FilterState) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if f.source_slug:
        clauses.append("e.source_slug = ?")
        params.append(f.source_slug)
    year_sql, year_params = query_util.year_clause("e", f.year_start, f.year_end)
    if year_sql != "1=1":
        clauses.append(year_sql)
        params.extend(year_params)
    if not clauses:
        return "1=1", []
    return " AND ".join(clauses), params


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def _empty_bounds(year: int = 2020) -> dict[str, Any]:
    return {
        "min_year": year,
        "max_year": year,
        "first_day": None,
        "last_day": None,
        "sources": [],
        "source_by_label": {},
    }


def list_sources(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    if not query_util.has_table(conn, "custom", "sources"):
        return []
    frame = _query_df(
        conn,
        """
        SELECT slug, label, icon, timezone, grain, entity_column, value_column
        FROM custom.sources
        ORDER BY label, slug
        """,
    )
    sources: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        sources.append(
            {
                "slug": row.slug,
                "label": row.label or row.slug,
                "icon": row.icon or "lucide:puzzle",
                "timezone": row.timezone or "Europe/Paris",
                "grain": row.grain or "one row per event",
                "has_entity": bool(row.entity_column),
                "has_value": bool(row.value_column),
            }
        )
    return sources


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    if not query_util.has_table(conn, "custom", "events"):
        return _empty_bounds()
    row = conn.execute("""
        SELECT
            min(year)::INT,
            max(year)::INT,
            min(CAST(ts_local AS DATE)),
            max(CAST(ts_local AS DATE))
        FROM custom.events
        WHERE ts_local IS NOT NULL
        """).fetchone()
    sources = list_sources(conn)
    labels: dict[str, str] = {}
    seen: dict[str, int] = {}
    for source in sources:
        seen[source["label"]] = seen.get(source["label"], 0) + 1
    for source in sources:
        label = source["label"]
        if seen[label] > 1:
            label = f"{label} ({source['slug']})"
        labels[label] = source["slug"]
        source["option"] = label
    if row is None or row[0] is None or row[1] is None:
        bounds = _empty_bounds()
        bounds["sources"] = sources
        bounds["source_by_label"] = labels
        return bounds
    return {
        "min_year": int(row[0]),
        "max_year": int(row[1]),
        "first_day": row[2],
        "last_day": row[3],
        "sources": sources,
        "source_by_label": labels,
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    source_label: str,
) -> FilterState:
    slug = bounds.get("source_by_label", {}).get(source_label)
    label = source_label if slug else None
    ys = year_start if year_start > bounds["min_year"] else None
    ye = year_end if year_end < bounds["max_year"] else None
    return FilterState(
        source_slug=slug,
        source_label=label,
        year_start=ys,
        year_end=ye,
    )


def previous_window(f: FilterState) -> FilterState | None:
    bounds = query_util.previous_year_bounds(f.year_start, f.year_end)
    if bounds is None:
        return None
    return FilterState(
        source_slug=f.source_slug,
        source_label=f.source_label,
        year_start=bounds[0],
        year_end=bounds[1],
    )


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    frame = _query_df(
        conn,
        f"""
        SELECT
            count(*)::BIGINT AS events,
            count(DISTINCT CAST(e.ts_local AS DATE))::BIGINT AS active_days,
            count(DISTINCT CASE WHEN e.entity <> '' THEN e.entity END)::BIGINT AS entities,
            coalesce(sum(e.value), 0)::DOUBLE AS value_sum
        FROM custom.events e
        WHERE {where}
        """,
        params,
    )
    streaks = streak_table(conn, f)
    frame["longest_streak"] = int(streaks["days"].max()) if not streaks.empty else 0
    return frame


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


def events_monthly(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT
            printf('%04d-%02d', e.year, e.month) AS year_month,
            count(*)::BIGINT AS events,
            coalesce(sum(e.value), 0)::DOUBLE AS value
        FROM custom.events e
        WHERE {where}
        GROUP BY e.year, e.month
        ORDER BY 1
        """,
        params,
    )


def events_daily(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT CAST(e.ts_local AS DATE) AS day, count(*)::BIGINT AS events
        FROM custom.events e
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def events_by_entity(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 30
) -> pd.DataFrame:
    where, params = _where(f)
    params = [*params, limit]
    return _query_df(
        conn,
        f"""
        SELECT
            e.entity,
            count(*)::BIGINT AS events,
            coalesce(sum(e.value), 0)::DOUBLE AS value
        FROM custom.events e
        WHERE {where} AND e.entity <> ''
        GROUP BY e.entity
        ORDER BY events DESC, e.entity
        LIMIT ?
        """,
        params,
    )


def weekday_heatmap(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        SELECT e.dow::INT AS dow, e.hour::INT AS hour, count(*)::BIGINT AS events
        FROM custom.events e
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def streak_table(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        WITH days AS (
            SELECT DISTINCT CAST(e.ts_local AS DATE) AS day
            FROM custom.events e
            WHERE {where}
        ),
        grouped AS (
            SELECT
                day,
                day - CAST(row_number() OVER (ORDER BY day) AS INTEGER) AS grp
            FROM days
        )
        SELECT
            min(day) AS start_day,
            max(day) AS end_day,
            count(*)::INT AS days
        FROM grouped
        GROUP BY grp
        ORDER BY days DESC, start_day
        LIMIT 8
        """,
        params,
    )


def forgotten_entities(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Entities whose last year is at least two years behind the window max."""
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        WITH scoped AS (
            SELECT e.entity, e.year
            FROM custom.events e
            WHERE {where} AND e.entity <> ''
        ),
        span AS (SELECT max(year) AS max_year FROM scoped),
        ents AS (
            SELECT entity, min(year)::INT AS first_year, max(year)::INT AS last_year,
                   count(*)::BIGINT AS events
            FROM scoped
            GROUP BY entity
        )
        SELECT ents.entity, ents.first_year, ents.last_year, ents.events
        FROM ents, span
        WHERE span.max_year IS NOT NULL
          AND ents.last_year <= span.max_year - 2
        ORDER BY ents.events DESC, ents.entity
        LIMIT 30
        """,
        params,
    )


def comeback_entities(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    """Entities with a gap of two or more years between active years."""
    where, params = _where(f)
    return _query_df(
        conn,
        f"""
        WITH years AS (
            SELECT e.entity, e.year
            FROM custom.events e
            WHERE {where} AND e.entity <> ''
            GROUP BY 1, 2
        ),
        gaps AS (
            SELECT
                entity,
                year,
                year - lag(year) OVER (PARTITION BY entity ORDER BY year) AS gap_years
            FROM years
        )
        SELECT entity, max(gap_years)::INT AS gap_years
        FROM gaps
        WHERE gap_years >= 2
        GROUP BY entity
        ORDER BY gap_years DESC, entity
        LIMIT 30
        """,
        params,
    )


def source_meta(bounds: dict[str, Any], slug: str | None) -> dict[str, Any] | None:
    for source in bounds.get("sources") or []:
        if source["slug"] == slug:
            return source
    return None
