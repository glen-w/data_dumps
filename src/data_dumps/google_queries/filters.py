"""Google Takeout queries — filters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util

# Noise calendar names (matched lowercased). Also exclude any name containing 'nba'.
_NOISE_CALENDAR_NAMES: tuple[str, ...] = (
    "sleep",
    "sleep(1)",
    "daily briefing",
    "nba 2022-23 schedule",
)


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    calendar: str | None = None
    exclude_noise: bool = True

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        chip = query_util.year_chip(self.year_start, self.year_end)
        if chip is not None:
            chips.append(chip)
        if self.calendar:
            chips.append(("calendar", f"calendar: {self.calendar}"))
        if self.exclude_noise:
            chips.append(("exclude_noise", "hide noise calendars"))
        return chips


def _year_where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    where, params = query_util.year_clause(alias, f.year_start, f.year_end)
    return where, params


def _noise_clause(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    """Exclude known noise calendars unless an explicit calendar lock is set."""
    if not f.exclude_noise or f.calendar:
        return "1=1", []
    p = f"{alias}." if alias else ""
    placeholders = ", ".join("?" for _ in _NOISE_CALENDAR_NAMES)
    clause = (
        f"({p}calendar_name IS NULL OR ("
        f"lower({p}calendar_name) NOT IN ({placeholders}) "
        f"AND {p}calendar_name NOT ILIKE '%nba%'"
        f"))"
    )
    return clause, list(_NOISE_CALENDAR_NAMES)


def _cal_where(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    where, params = _year_where(alias, f)
    if f.calendar:
        p = f"{alias}." if alias else ""
        extra = f"{p}calendar_name = ?"
        where = f"({where}) AND {extra}" if where != "1=1" else extra
        params = [*params, f.calendar]
    noise_w, noise_p = _noise_clause(alias, f)
    if noise_w != "1=1":
        where = f"({where}) AND {noise_w}" if where != "1=1" else noise_w
        params = [*params, *noise_p]
    return where, params


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def previous_window(f: FilterState) -> FilterState | None:
    bounds = query_util.previous_year_bounds(f.year_start, f.year_end)
    if bounds is None:
        return None
    return FilterState(
        year_start=bounds[0],
        year_end=bounds[1],
        calendar=f.calendar,
        exclude_noise=f.exclude_noise,
    )


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT, max(year)::INT,
            min(day)::DATE, max(day)::DATE
        FROM (
            SELECT year, day FROM google.calendar_events WHERE day IS NOT NULL
            UNION ALL
            SELECT year, day FROM google.photos WHERE day IS NOT NULL
            UNION ALL
            SELECT year, day FROM google.activity WHERE day IS NOT NULL
            UNION ALL
            SELECT year, day FROM google.maps_saves WHERE day IS NOT NULL
            UNION ALL
            SELECT year, day FROM google.play_installs WHERE day IS NOT NULL
        )
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2015, 2015
    calendars = [r[0] for r in conn.execute("""
            SELECT calendar_name, count(*) AS n
            FROM google.calendar_events
            WHERE calendar_name IS NOT NULL
            GROUP BY 1
            ORDER BY n DESC, calendar_name
            """).fetchall() if r[0]]
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "calendars": calendars,
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int | None,
    year_end: int | None,
    calendar: str | None = None,
    exclude_noise: bool = True,
) -> FilterState:
    ys = int(year_start) if year_start is not None else bounds.get("min_year")
    ye = int(year_end) if year_end is not None else bounds.get("max_year")
    if ys is not None and ye is not None and ys > ye:
        ys, ye = ye, ys
    mn, mx = bounds.get("min_year"), bounds.get("max_year")
    if ys is not None and mn is not None:
        ys = max(int(ys), int(mn))
    if ye is not None and mx is not None:
        ye = min(int(ye), int(mx))
    if ys is not None and ye is not None and ys > ye:
        ys, ye = ye, ys
    cal = None if not calendar or calendar == "(all)" else calendar
    return FilterState(
        year_start=ys,
        year_end=ye,
        calendar=cal,
        exclude_noise=bool(exclude_noise),
    )
