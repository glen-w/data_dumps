"""Warehouse-wide counts for the explorer homepage.

Row totals come from ``duckdb_tables().estimated_size`` (exact for tables this
process created). Tables in one schema roll up to that schema's explorer tab,
so Spotify Account Data counts under Spotify.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import duckdb
import pandas as pd

from data_dumps.contributions import explorer_contributions
from data_dumps.query_util import has_table

_SYSTEM_SCHEMAS = frozenset({"information_schema", "pg_catalog"})


@dataclass(frozen=True)
class SourceStat:
    slug: str
    label: str
    rows: int
    tables: int
    first_day: date | None
    last_day: date | None
    min_year: int | None
    max_year: int | None


@dataclass(frozen=True)
class WarehouseOverview:
    sources: tuple[SourceStat, ...]
    n_sources: int
    n_rows: int
    n_tables: int
    first_day: date | None
    last_day: date | None
    min_year: int | None
    max_year: int | None

    @property
    def n_years(self) -> int | None:
        if self.min_year is None or self.max_year is None:
            return None
        return self.max_year - self.min_year + 1


def warehouse_overview(
    conn: duckdb.DuckDBPyConnection,
    *,
    bounds_by_slug: Mapping[str, dict[str, Any] | None] | None = None,
) -> WarehouseOverview:
    """Sources with a gate table or any rows, plus span across their bounds.

    ``bounds_by_slug`` skips a second ``data_bounds`` pass when the explorer
    already computed one. ``None`` means that slug is not ingested.
    """
    aggs = _schema_aggs(conn)
    sources: list[SourceStat] = []
    seen: set[str] = set()
    for contribution in explorer_contributions():
        assert contribution.gate_table is not None
        assert contribution.tab_label is not None
        schema, table = contribution.gate_table
        bounds, present = _bounds_for(
            conn,
            contribution.slug,
            schema,
            table,
            contribution.data_bounds,
            bounds_by_slug,
        )
        agg = aggs.get(schema)
        rows = agg[0] if agg else 0
        tables = agg[1] if agg else 0
        if not present and tables == 0:
            continue
        sources.append(
            _source_stat(
                slug=contribution.slug,
                label=contribution.tab_label,
                rows=rows,
                tables=tables,
                bounds=bounds if present else None,
            )
        )
        seen.add(schema)

    for schema, (rows, tables) in aggs.items():
        if schema in seen or tables == 0:
            continue
        sources.append(
            SourceStat(
                slug=schema,
                label=schema.replace("_", " ").title(),
                rows=rows,
                tables=tables,
                first_day=None,
                last_day=None,
                min_year=None,
                max_year=None,
            )
        )

    sources.sort(key=lambda s: s.label.casefold())
    first_days = [s.first_day for s in sources if s.first_day is not None]
    last_days = [s.last_day for s in sources if s.last_day is not None]
    min_years = [s.min_year for s in sources if s.min_year is not None]
    max_years = [s.max_year for s in sources if s.max_year is not None]
    return WarehouseOverview(
        sources=tuple(sources),
        n_sources=len(sources),
        n_rows=sum(s.rows for s in sources),
        n_tables=sum(s.tables for s in sources),
        first_day=min(first_days) if first_days else None,
        last_day=max(last_days) if last_days else None,
        min_year=min(min_years) if min_years else None,
        max_year=max(max_years) if max_years else None,
    )


def sources_frame(overview: WarehouseOverview) -> pd.DataFrame:
    """One row per ingested source, largest first."""
    ranked = sorted(overview.sources, key=lambda s: (-s.rows, s.label.casefold()))
    return pd.DataFrame(
        [
            {
                "Source": s.label,
                "Rows": s.rows,
                "Tables": s.tables,
                "First": _fmt_day(s.first_day),
                "Last": _fmt_day(s.last_day),
                "Years": _fmt_years(s.min_year, s.max_year),
            }
            for s in ranked
        ],
        columns=["Source", "Rows", "Tables", "First", "Last", "Years"],
    )


def _bounds_for(
    conn: duckdb.DuckDBPyConnection,
    slug: str,
    schema: str,
    table: str,
    data_bounds: Any,
    bounds_by_slug: Mapping[str, dict[str, Any] | None] | None,
) -> tuple[dict[str, Any] | None, bool]:
    if bounds_by_slug is not None and slug in bounds_by_slug:
        bounds = bounds_by_slug[slug]
        return bounds, bounds is not None
    present = has_table(conn, schema, table)
    if not present or data_bounds is None:
        return None, present
    bounds = data_bounds(conn)
    return bounds, True


def _source_stat(
    *,
    slug: str,
    label: str,
    rows: int,
    tables: int,
    bounds: dict[str, Any] | None,
) -> SourceStat:
    return SourceStat(
        slug=slug,
        label=label,
        rows=rows,
        tables=tables,
        first_day=_as_date(bounds.get("first_day")) if bounds else None,
        last_day=_as_date(bounds.get("last_day")) if bounds else None,
        min_year=_as_int(bounds.get("min_year")) if bounds else None,
        max_year=_as_int(bounds.get("max_year")) if bounds else None,
    )


def _schema_aggs(conn: duckdb.DuckDBPyConnection) -> dict[str, tuple[int, int]]:
    listed = conn.execute("""
        SELECT schema_name, table_name, estimated_size
        FROM duckdb_tables()
        WHERE NOT COALESCE(internal, false)
          AND NOT COALESCE(temporary, false)
          AND schema_name NOT IN ('information_schema', 'pg_catalog')
        """).fetchall()
    rows_by_schema: dict[str, int] = defaultdict(int)
    tables_by_schema: dict[str, int] = defaultdict(int)
    for schema, table, estimated in listed:
        if schema in _SYSTEM_SCHEMAS:
            continue
        n = (
            int(estimated)
            if estimated is not None
            else _count_rows(conn, schema, table)
        )
        rows_by_schema[schema] += n
        tables_by_schema[schema] += 1
    return {
        schema: (rows_by_schema[schema], tables_by_schema[schema])
        for schema in tables_by_schema
    }


def _count_rows(conn: duckdb.DuckDBPyConnection, schema: str, table: str) -> int:
    quoted = f"{_quote(schema)}.{_quote(table)}"
    row = conn.execute(f"SELECT count(*)::BIGINT FROM {quoted}").fetchone()
    return int(row[0]) if row else 0


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _as_date(value: Any) -> date | None:
    if value is None or _is_na(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    to_py = getattr(value, "to_pydatetime", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, datetime):
            return converted.date()
        if isinstance(converted, date):
            return converted
    return None


def _as_int(value: Any) -> int | None:
    if value is None or _is_na(value):
        return None
    return int(value)


def _is_na(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _fmt_day(value: date | None) -> str:
    return value.isoformat() if value else "—"


def _fmt_years(min_year: int | None, max_year: int | None) -> str:
    if min_year is None or max_year is None:
        return "—"
    if min_year == max_year:
        return str(min_year)
    return f"{min_year} → {max_year}"
