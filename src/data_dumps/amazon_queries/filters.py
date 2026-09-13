"""Amazon filter state and shared SQL helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    marketplaces: list[str] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    dept_families: list[str] = field(default_factory=list)
    include_cancelled: bool = False

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        if self.marketplaces:
            chips.append(("marketplaces", "mkts " + ",".join(self.marketplaces)))
        if self.currencies:
            chips.append(("currencies", "fx " + ",".join(self.currencies)))
        if self.dept_families:
            chips.append(("dept_families", "types " + ",".join(self.dept_families)))
        if self.include_cancelled:
            chips.append(("cancelled", "incl. cancelled"))
        return chips


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    marketplaces: list[str] | None = None,
    currencies: list[str] | None = None,
    dept_families: list[str] | None = None,
    include_cancelled: bool = False,
) -> FilterState:
    return FilterState(
        year_start=year_start,
        year_end=year_end,
        marketplaces=list(marketplaces or []),
        currencies=list(currencies or []),
        dept_families=list(dept_families or []),
        include_cancelled=include_cancelled,
    )


def _year_clause(alias: str, f: FilterState) -> tuple[str, list[Any]]:
    return query_util.year_clause(alias, f.year_start, f.year_end)


def _item_where(f: FilterState, alias: str = "i") -> tuple[str, list[Any]]:
    parts: list[str] = []
    params: list[Any] = []
    yw, yp = _year_clause(alias, f)
    if yw != "1=1":
        parts.append(yw)
        params.extend(yp)
    if not f.include_cancelled:
        parts.append(f"NOT {alias}.is_cancelled")
    if f.marketplaces:
        placeholders = ", ".join("?" for _ in f.marketplaces)
        parts.append(f"{alias}.marketplace IN ({placeholders})")
        params.extend(f.marketplaces)
    if f.currencies:
        placeholders = ", ".join("?" for _ in f.currencies)
        parts.append(f"{alias}.currency IN ({placeholders})")
        params.extend(f.currencies)
    if f.dept_families:
        placeholders = ", ".join("?" for _ in f.dept_families)
        parts.append(f"{alias}.dept_family IN ({placeholders})")
        params.extend(f.dept_families)
    where = " AND ".join(parts) if parts else "1=1"
    return where, params


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def has_table(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return query_util.has_table(conn, "amazon", table)


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT,
            max(year)::INT,
            min(order_ts_local)::DATE,
            max(order_ts_local)::DATE
        FROM amazon.order_items
        WHERE year IS NOT NULL
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        # Fall back to alexa intents
        row2 = conn.execute("""
            SELECT min(year)::INT, max(year)::INT
            FROM amazon.alexa_intents WHERE year IS NOT NULL
            """).fetchone()
        if row2 and row2[0] is not None:
            min_year, max_year = row2[0], row2[1]
        else:
            min_year, max_year = 2015, 2026
    marketplaces = [r[0] for r in conn.execute("""
            SELECT DISTINCT marketplace FROM amazon.order_items
            WHERE marketplace IS NOT NULL ORDER BY 1
            """).fetchall()]
    currencies = [r[0] for r in conn.execute("""
            SELECT DISTINCT currency FROM amazon.order_items
            WHERE currency IS NOT NULL ORDER BY 1
            """).fetchall()]
    families = [r[0] for r in conn.execute("""
            SELECT DISTINCT dept_family FROM amazon.order_items
            WHERE dept_family IS NOT NULL ORDER BY 1
            """).fetchall()]
    return {
        "min_year": int(min_year),
        "max_year": int(max_year),
        "first_day": row[2],
        "last_day": row[3],
        "marketplaces": marketplaces,
        "currencies": currencies,
        "dept_families": families,
    }
