"""Filter state and DuckDB queries for the browser-history Marimo dashboard.

Grain is URL-level (last visit + visit count), not individual visits.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

NARRATIVE_CONTEXT_KEYS = frozenset(
    {
        "filter_digest",
        "filters",
        "scoreboard",
        "top_domains",
        "top_pages",
        "categories",
        "searches",
        "forgotten",
        "routines",
    }
)


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    categories: list[str] = field(default_factory=list)
    schemes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    include_private: bool = True
    text_search: str | None = None
    etld1: str | None = None

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        if self.year_start is not None or self.year_end is not None:
            ys = self.year_start if self.year_start is not None else "…"
            ye = self.year_end if self.year_end is not None else "…"
            chips.append(("year_range", f"years {ys}–{ye}"))
        for c in self.categories:
            chips.append(("category", f"cat={c}"))
        for s in self.schemes:
            chips.append(("scheme", f"scheme={s}"))
        for src in self.sources:
            chips.append(("source", f"src={src}"))
        if not self.include_private:
            chips.append(("private", "hide private/LAN"))
        if self.text_search:
            chips.append(("text_search", f"search: {self.text_search}"))
        if self.etld1:
            chips.append(("etld1", f"domain: {self.etld1}"))
        return chips

    def filter_digest(self) -> str:
        payload = {
            "year_start": self.year_start,
            "year_end": self.year_end,
            "categories": sorted(self.categories),
            "schemes": sorted(self.schemes),
            "sources": sorted(self.sources),
            "include_private": self.include_private,
            "text_search": self.text_search,
            "etld1": self.etld1,
        }
        blob = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()


def has_table(conn: duckdb.DuckDBPyConnection, table: str = "pages") -> bool:
    row = conn.execute(
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'browser' AND table_name = ?
        """,
        [table],
    ).fetchone()
    return row is not None and row[0] > 0


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    span = conn.execute(
        """
        SELECT min(year)::INTEGER, max(year)::INTEGER,
               min(local_date), max(local_date)
        FROM browser.pages
        """
    ).fetchone()
    cats = [
        r[0]
        for r in conn.execute(
            """
            SELECT category FROM browser.pages
            WHERE category IS NOT NULL
            GROUP BY 1 ORDER BY count(*) DESC
            """
        ).fetchall()
    ]
    schemes = [
        r[0]
        for r in conn.execute(
            """
            SELECT scheme FROM browser.pages
            WHERE scheme IS NOT NULL
            GROUP BY 1 ORDER BY count(*) DESC
            """
        ).fetchall()
    ]
    # Distinct source labels from comma-separated column
    source_rows = conn.execute("SELECT DISTINCT sources FROM browser.pages").fetchall()
    sources: set[str] = set()
    for (blob,) in source_rows:
        if not blob:
            continue
        for part in str(blob).split(","):
            part = part.strip()
            if part:
                sources.add(part)
    return {
        "min_year": int(span[0]) if span and span[0] is not None else 2020,
        "max_year": int(span[1]) if span and span[1] is not None else 2026,
        "first_day": span[2] if span else None,
        "last_day": span[3] if span else None,
        "categories": cats,
        "schemes": schemes,
        "sources": sorted(sources),
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int,
    year_end: int,
    categories: list[str] | None = None,
    schemes: list[str] | None = None,
    sources: list[str] | None = None,
    include_private: bool = True,
    text_search: str | None = None,
    etld1: str | None = None,
) -> FilterState:
    ys = int(year_start) if year_start else bounds["min_year"]
    ye = int(year_end) if year_end else bounds["max_year"]
    search = (text_search or "").strip() or None
    domain = (etld1 or "").strip() or None
    return FilterState(
        year_start=ys,
        year_end=ye,
        categories=list(categories or []),
        schemes=list(schemes or []),
        sources=list(sources or []),
        include_private=include_private,
        text_search=search,
        etld1=domain,
    )


def _pages_where(f: FilterState, alias: str = "p") -> tuple[str, list[Any]]:
    clauses: list[str] = ["1=1"]
    params: list[Any] = []
    if f.year_start is not None:
        clauses.append(f"{alias}.year >= ?")
        params.append(f.year_start)
    if f.year_end is not None:
        clauses.append(f"{alias}.year <= ?")
        params.append(f.year_end)
    if f.categories:
        placeholders = ",".join("?" for _ in f.categories)
        clauses.append(f"{alias}.category IN ({placeholders})")
        params.extend(f.categories)
    if f.schemes:
        placeholders = ",".join("?" for _ in f.schemes)
        clauses.append(f"{alias}.scheme IN ({placeholders})")
        params.extend(f.schemes)
    if f.sources:
        src_clauses = []
        for src in f.sources:
            src_clauses.append(
                f"(',' || {alias}.sources || ',' LIKE '%,' || ? || ',%')"
            )
            params.append(src)
        clauses.append("(" + " OR ".join(src_clauses) + ")")
    if not f.include_private:
        clauses.append(f"NOT {alias}.is_private")
    if f.text_search:
        clauses.append(
            f"(lower(coalesce({alias}.title,'')) LIKE ? "
            f"OR lower(coalesce({alias}.host,'')) LIKE ? "
            f"OR lower(coalesce({alias}.url,'')) LIKE ? "
            f"OR lower(coalesce({alias}.search_query,'')) LIKE ?)"
        )
        needle = f"%{f.text_search.lower()}%"
        params.extend([needle, needle, needle, needle])
    if f.etld1:
        clauses.append(f"{alias}.etld1 = ?")
        params.append(f.etld1)
    return " AND ".join(clauses), params


def scoreboard(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    compare: bool = False,
) -> pd.DataFrame:
    cur = _scoreboard_row(conn, f)
    if not compare or f.year_start is None or f.year_end is None:
        return cur
    span = f.year_end - f.year_start + 1
    prev = FilterState(
        year_start=f.year_start - span,
        year_end=f.year_start - 1,
        categories=list(f.categories),
        schemes=list(f.schemes),
        sources=list(f.sources),
        include_private=f.include_private,
        text_search=f.text_search,
        etld1=f.etld1,
    )
    prev_df = _scoreboard_row(conn, prev)
    if cur.empty or prev_df.empty:
        return cur
    out = cur.copy()
    for col in cur.columns:
        if col == "label":
            continue
        if col in prev_df.columns:
            out[f"prev_{col}"] = prev_df.iloc[0][col]
    return out


def _scoreboard_row(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT
          'current' AS label,
          count(*)::BIGINT AS unique_urls,
          coalesce(sum(visit_count), 0)::BIGINT AS visit_sum,
          count(*) FILTER (WHERE is_private)::BIGINT AS private_urls,
          count(*) FILTER (WHERE search_query IS NOT NULL)::BIGINT AS search_urls,
          count(DISTINCT etld1)::BIGINT AS distinct_domains,
          count(DISTINCT category)::BIGINT AS categories,
          min(local_date) AS first_day,
          max(local_date) AS last_day
        FROM browser.pages p
        WHERE {where}
        """,
        params,
    )


def top_domains(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT etld1 AS domain,
               count(*)::BIGINT AS urls,
               sum(visit_count)::BIGINT AS visits,
               max(local_date) AS last_seen,
               any_value(category) AS category
        FROM browser.pages p
        WHERE {where} AND etld1 IS NOT NULL
        GROUP BY 1
        ORDER BY visits DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def top_hosts(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT host,
               count(*)::BIGINT AS urls,
               sum(visit_count)::BIGINT AS visits,
               max(local_date) AS last_seen,
               any_value(category) AS category
        FROM browser.pages p
        WHERE {where} AND host IS NOT NULL
        GROUP BY 1
        ORDER BY visits DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def top_pages(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 30
) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT coalesce(title, url) AS title, url, host, etld1, category,
               visit_count AS visits, local_date AS last_seen, sources
        FROM browser.pages p
        WHERE {where}
        ORDER BY visit_count DESC, last_visit_utc DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def category_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT category,
               count(*)::BIGINT AS urls,
               sum(visit_count)::BIGINT AS visits
        FROM browser.pages p
        WHERE {where}
        GROUP BY 1
        ORDER BY visits DESC
        """,
        params,
    )


def scheme_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT scheme,
               count(*)::BIGINT AS urls,
               sum(visit_count)::BIGINT AS visits
        FROM browser.pages p
        WHERE {where}
        GROUP BY 1
        ORDER BY visits DESC
        """,
        params,
    )


def source_mix(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT sources AS source_set,
               count(*)::BIGINT AS urls,
               sum(visit_count)::BIGINT AS visits
        FROM browser.pages p
        WHERE {where}
        GROUP BY 1
        ORDER BY urls DESC
        """,
        params,
    )


def monthly_last_visits(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT date_trunc('month', local_date)::DATE AS month,
               count(*)::BIGINT AS urls_last_seen,
               sum(visit_count)::BIGINT AS visit_sum
        FROM browser.pages p
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def calendar_last_seen(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT local_date AS day,
               count(*)::BIGINT AS urls,
               sum(visit_count)::BIGINT AS visits
        FROM browser.pages p
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )


def search_engines(conn: duckdb.DuckDBPyConnection, f: FilterState) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT search_engine AS engine,
               count(*)::BIGINT AS urls,
               count(*) FILTER (WHERE search_query IS NOT NULL)::BIGINT AS with_query
        FROM browser.pages p
        WHERE {where} AND search_engine IS NOT NULL
        GROUP BY 1
        ORDER BY urls DESC
        """,
        params,
    )


def top_search_queries(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 40
) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT search_query AS query,
               search_engine AS engine,
               count(*)::BIGINT AS urls,
               sum(visit_count)::BIGINT AS visits,
               max(local_date) AS last_seen
        FROM browser.pages p
        WHERE {where} AND search_query IS NOT NULL
        GROUP BY 1, 2
        ORDER BY visits DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def monthly_search_volume(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> pd.DataFrame:
    """Search URLs by last-seen month (URL grain — not per-query events)."""
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT date_trunc('month', local_date)::DATE AS month,
               search_engine AS engine,
               count(*)::BIGINT AS urls,
               count(*) FILTER (WHERE search_query IS NOT NULL)::BIGINT AS with_query
        FROM browser.pages p
        WHERE {where} AND search_engine IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        params,
    )


def forgotten_gems(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    min_visits: int = 5,
    stale_days: int = 180,
    limit: int = 30,
) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT coalesce(title, url) AS title, url, host, etld1, category,
               visit_count AS visits, local_date AS last_seen,
               date_diff('day', local_date, current_date) AS days_ago
        FROM browser.pages p
        WHERE {where}
          AND visit_count >= ?
          AND date_diff('day', local_date, current_date) >= ?
        ORDER BY visit_count DESC, days_ago DESC
        LIMIT ?
        """,
        [*params, min_visits, stale_days, limit],
    )


def routines(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    min_visits: int = 10,
    recent_days: int = 60,
    limit: int = 25,
) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT host, etld1, category,
               count(*)::BIGINT AS urls,
               sum(visit_count)::BIGINT AS visits,
               max(local_date) AS last_seen
        FROM browser.pages p
        WHERE {where}
          AND host IS NOT NULL
          AND date_diff('day', local_date, current_date) <= ?
        GROUP BY 1, 2, 3
        HAVING sum(visit_count) >= ?
        ORDER BY visits DESC
        LIMIT ?
        """,
        [*params, recent_days, min_visits, limit],
    )


def comeback_domains(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 25
) -> pd.DataFrame:
    """Domains present in both source sets (legacy + sky)."""
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT etld1 AS domain,
               count(*)::BIGINT AS urls,
               sum(visit_count)::BIGINT AS visits,
               min(local_date) AS first_seen,
               max(local_date) AS last_seen
        FROM browser.pages p
        WHERE {where}
          AND etld1 IS NOT NULL
          AND sources LIKE '%firefox_sky%'
          AND sources LIKE '%legacy_chrome%'
        GROUP BY 1
        ORDER BY visits DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def local_hosts(
    conn: duckdb.DuckDBPyConnection, f: FilterState, *, limit: int = 30
) -> pd.DataFrame:
    where, params = _pages_where(f)
    return _query_df(
        conn,
        f"""
        SELECT host,
               count(*)::BIGINT AS urls,
               sum(visit_count)::BIGINT AS visits,
               max(local_date) AS last_seen
        FROM browser.pages p
        WHERE {where} AND is_private
        GROUP BY 1
        ORDER BY visits DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def path_tree(
    conn: duckdb.DuckDBPyConnection,
    f: FilterState,
    *,
    etld1: str,
    limit: int = 40,
) -> pd.DataFrame:
    """Path-prefix rollup for one registrable domain."""
    locked = FilterState(
        year_start=f.year_start,
        year_end=f.year_end,
        categories=list(f.categories),
        schemes=list(f.schemes),
        sources=list(f.sources),
        include_private=f.include_private,
        text_search=f.text_search,
        etld1=etld1,
    )
    where, params = _pages_where(locked)
    return _query_df(
        conn,
        f"""
        SELECT
          host,
          CASE
            WHEN path IS NULL OR path = '' OR path = '/' THEN '/'
            ELSE regexp_extract(path, '^(/[^/]*)', 1)
          END AS path_prefix,
          count(*)::BIGINT AS urls,
          sum(visit_count)::BIGINT AS visits
        FROM browser.pages p
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY visits DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def narrative_context(
    conn: duckdb.DuckDBPyConnection, f: FilterState
) -> dict[str, Any]:
    sb = scoreboard(conn, f)
    return {
        "filter_digest": f.filter_digest(),
        "filters": [label for _, label in f.chip_labels()],
        "scoreboard": sb.to_dict(orient="records"),
        "top_domains": top_domains(conn, f, limit=10).to_dict(orient="records"),
        "top_pages": top_pages(conn, f, limit=10).to_dict(orient="records"),
        "categories": category_mix(conn, f).to_dict(orient="records"),
        "searches": top_search_queries(conn, f, limit=10).to_dict(orient="records"),
        "forgotten": forgotten_gems(conn, f, limit=8).to_dict(orient="records"),
        "routines": routines(conn, f, limit=8).to_dict(orient="records"),
    }
