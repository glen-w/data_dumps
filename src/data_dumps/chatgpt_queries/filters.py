"""ChatGPT queries — filters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

from data_dumps import query_util

NARRATIVE_CONTEXT_KEYS = frozenset(
    {
        "filter_digest",
        "filters",
        "scoreboard",
        "streak",
        "model_mix",
        "top_conversations",
        "forgotten",
        "comebacks",
        "content_mix",
    }
)


@dataclass
class FilterState:
    year_start: int | None = None
    year_end: int | None = None
    roles: list[str] = field(default_factory=list)
    model_families: list[str] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    title_search: str | None = None
    conversation_id: str | None = None
    shared_only: bool = False

    def has_entity_lock(self) -> bool:
        return bool(self.conversation_id)

    def chip_labels(self) -> list[tuple[str, str]]:
        chips: list[tuple[str, str]] = []
        chip = query_util.year_chip(self.year_start, self.year_end)
        if chip is not None:
            chips.append(chip)
        for role in self.roles:
            chips.append(("role", f"role={role}"))
        for fam in self.model_families:
            chips.append(("model_family", f"model={fam}"))
        for ct in self.content_types:
            chips.append(("content_type", f"type={ct}"))
        if self.title_search:
            chips.append(("title_search", f"search: {self.title_search}"))
        if self.conversation_id:
            chips.append(("conversation_id", f"thread: {self.conversation_id[:8]}…"))
        if self.shared_only:
            chips.append(("shared_only", "shared only"))
        return chips

    def filter_digest(self) -> str:
        payload = {
            "year_start": self.year_start,
            "year_end": self.year_end,
            "roles": sorted(self.roles),
            "model_families": sorted(self.model_families),
            "content_types": sorted(self.content_types),
            "title_search": self.title_search,
            "conversation_id": self.conversation_id,
            "shared_only": self.shared_only,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def clear_field(self, field_name: str) -> None:
        if field_name == "year_range":
            self.year_start = None
            self.year_end = None
        elif field_name == "role":
            self.roles = []
        elif field_name == "model_family":
            self.model_families = []
        elif field_name == "content_type":
            self.content_types = []
        elif field_name == "title_search":
            self.title_search = None
        elif field_name == "conversation_id":
            self.conversation_id = None
        elif field_name == "shared_only":
            self.shared_only = False


def has_table(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return query_util.has_table(conn, "chatgpt", table)


def _query_df(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def _msg_where(f: FilterState, alias: str = "m") -> tuple[str, list[Any]]:
    p = f"{alias}."
    clauses: list[str] = [f"{p}ts_local IS NOT NULL"]
    params: list[Any] = []
    query_util.append_year_clause(clauses, params, alias, f.year_start, f.year_end)
    if f.roles:
        placeholders = ", ".join("?" for _ in f.roles)
        clauses.append(f"{p}role IN ({placeholders})")
        params.extend(f.roles)
    if f.model_families:
        placeholders = ", ".join("?" for _ in f.model_families)
        clauses.append(f"{p}model_family IN ({placeholders})")
        params.extend(f.model_families)
    if f.content_types:
        placeholders = ", ".join("?" for _ in f.content_types)
        clauses.append(f"{p}content_type IN ({placeholders})")
        params.extend(f.content_types)
    if f.conversation_id:
        clauses.append(f"{p}conversation_id = ?")
        params.append(f.conversation_id)
    if f.title_search or f.shared_only:
        sub: list[str] = [
            f"c.conversation_id = {p}conversation_id",
        ]
        if f.title_search:
            sub.append("contains(lower(coalesce(c.title, '')), lower(?))")
            params.append(f.title_search)
        if f.shared_only:
            sub.append("c.is_shared")
        clauses.append(
            "exists (SELECT 1 FROM chatgpt.conversations c WHERE "
            + " AND ".join(sub)
            + ")"
        )
    return " AND ".join(clauses), params


def _conv_where(f: FilterState, alias: str = "c") -> tuple[str, list[Any]]:
    p = f"{alias}."
    clauses: list[str] = []
    params: list[Any] = []
    query_util.append_year_clause(clauses, params, alias, f.year_start, f.year_end)
    if f.conversation_id:
        clauses.append(f"{p}conversation_id = ?")
        params.append(f.conversation_id)
    if f.title_search:
        clauses.append(f"contains(lower(coalesce({p}title, '')), lower(?))")
        params.append(f.title_search)
    if f.shared_only:
        clauses.append(f"{p}is_shared")
    if f.model_families:
        placeholders = ", ".join("?" for _ in f.model_families)
        clauses.append(f"{p}default_model_family IN ({placeholders})")
        params.extend(f.model_families)
    return (" AND ".join(clauses) if clauses else "1=1"), params


def data_bounds(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute("""
        SELECT
            min(year)::INT, max(year)::INT,
            min(ts_local)::DATE, max(ts_local)::DATE
        FROM chatgpt.messages
        WHERE ts_local IS NOT NULL
        """).fetchone()
    assert row is not None
    min_year, max_year = row[0], row[1]
    if min_year is None or max_year is None:
        min_year, max_year = 2023, 2023
    roles = [
        r[0]
        for r in conn.execute(
            "SELECT role FROM chatgpt.messages WHERE role IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC"
        ).fetchall()
        if r[0]
    ]
    families = [r[0] for r in conn.execute("""
            SELECT model_family FROM chatgpt.messages
            WHERE model_family IS NOT NULL
            GROUP BY 1 ORDER BY count(*) DESC
            """).fetchall() if r[0]]
    content_types = [r[0] for r in conn.execute("""
            SELECT content_type FROM chatgpt.messages
            WHERE content_type IS NOT NULL
            GROUP BY 1 ORDER BY count(*) DESC
            """).fetchall() if r[0]]
    n_shared = conn.execute("SELECT count(*)::BIGINT FROM chatgpt.shared").fetchone()
    return {
        "min_year": min_year,
        "max_year": max_year,
        "first_day": row[2],
        "last_day": row[3],
        "roles": roles,
        "model_families": families,
        "content_types": content_types,
        "n_shared": int(n_shared[0]) if n_shared else 0,
    }


def filter_from_widgets(
    bounds: dict[str, Any],
    *,
    year_start: int | None,
    year_end: int | None,
    roles: list[str] | None = None,
    model_families: list[str] | None = None,
    content_types: list[str] | None = None,
    title_search: str = "",
    conversation_id: str | None = None,
    shared_only: bool = False,
) -> FilterState:
    ys = year_start if year_start is not None else bounds.get("min_year")
    ye = year_end if year_end is not None else bounds.get("max_year")
    # Treat full span as no year filter for compare windows.
    if ys == bounds.get("min_year") and ye == bounds.get("max_year"):
        pass  # keep explicit years for scoreboard compare
    return FilterState(
        year_start=ys,
        year_end=ye,
        roles=list(roles or []),
        model_families=list(model_families or []),
        content_types=list(content_types or []),
        title_search=(title_search or "").strip() or None,
        conversation_id=conversation_id or None,
        shared_only=bool(shared_only),
    )
