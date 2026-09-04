"""Extension point for future dumps (Reddit, Amazon, …)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import duckdb


@runtime_checkable
class Source(Protocol):
    """One platform export. Implement when a new dump is in hand."""

    name: str

    def detect(self, path: Path) -> bool:
        """Return True if this loader owns the given zip or directory."""
        ...

    def load(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        """Ingest into DuckDB (create/replace tables)."""
        ...

    def tables(self) -> list[str]:
        """Qualified table names this source provides."""
        ...

    def inventory(self, conn: duckdb.DuckDBPyConnection) -> dict:
        """Row counts / span for the CLI. Must include a 'summary' string."""
        ...
