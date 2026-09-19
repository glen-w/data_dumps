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


def year_chip(
    year_start: int | None,
    year_end: int | None,
) -> tuple[str, str] | None:
    """``("year_range", "years {start}–{end}")``, or None when both ends are open."""
    if year_start is None and year_end is None:
        return None
    ys = year_start if year_start is not None else "…"
    ye = year_end if year_end is not None else "…"
    return ("year_range", f"years {ys}–{ye}")


def append_year_clause(
    clauses: list[str],
    params: list[Any],
    alias: str,
    year_start: int | None,
    year_end: int | None,
) -> None:
    """Append :func:`year_clause` when a bound is set. Skips the open ``1=1``."""
    where, year_params = year_clause(alias, year_start, year_end)
    if where == "1=1":
        return
    clauses.append(where)
    params.extend(year_params)


def previous_year_bounds(
    year_start: int | None, year_end: int | None
) -> tuple[int, int] | None:
    """Equal-length window immediately before ``[year_start, year_end]``."""
    if year_start is None or year_end is None:
        return None
    span = year_end - year_start
    return year_start - span - 1, year_start - 1
