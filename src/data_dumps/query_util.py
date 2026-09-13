"""Shared DuckDB helpers for source query modules."""

from __future__ import annotations

from typing import Any

import duckdb


def has_table(conn: duckdb.DuckDBPyConnection, schema: str, table: str) -> bool:
    row = conn.execute(
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ?
        """,
        [schema, table],
    ).fetchone()
    return row is not None and row[0] > 0


def year_clause(
    alias: str,
    year_start: int | None,
    year_end: int | None,
) -> tuple[str, list[Any]]:
    """Build ``alias.year >= ? AND alias.year <= ?`` (or ``1=1`` when open)."""
    clauses: list[str] = []
    params: list[Any] = []
    prefix = f"{alias}." if alias else ""
    if year_start is not None:
        clauses.append(f"{prefix}year >= ?")
        params.append(year_start)
    if year_end is not None:
        clauses.append(f"{prefix}year <= ?")
        params.append(year_end)
    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def previous_year_bounds(
    year_start: int | None, year_end: int | None
) -> tuple[int, int] | None:
    """Equal-length window immediately before ``[year_start, year_end]``."""
    if year_start is None or year_end is None:
        return None
    span = year_end - year_start
    return year_start - span - 1, year_start - 1
