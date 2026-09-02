#!/usr/bin/env python3
"""CLI: ingest a GDPR dump zip into the local DuckDB warehouse."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

from data_dumps.sources.spotify import SpotifySource

SOURCES = [SpotifySource()]
DEFAULT_DB = Path(__file__).resolve().parents[2] / "warehouse" / "catalog.duckdb"


def pick_source(path: Path):
    for source in SOURCES:
        if source.detect(path):
            return source
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest a GDPR data dump into DuckDB")
    parser.add_argument("path", type=Path, help="Path to zip or extracted folder")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"DuckDB catalog path (default: {DEFAULT_DB})",
    )
    args = parser.parse_args(argv)

    path = args.path.resolve()
    if not path.exists():
        print(f"error: not found: {path}", file=sys.stderr)
        return 1

    source = pick_source(path)
    if source is None:
        print("error: no loader matched this path", file=sys.stderr)
        return 1

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(args.db))
    try:
        print(f"loading {path.name} via {source.name}…")
        source.load(path, conn)
        inv = source.inventory(conn)
        print(
            f"spotify.plays: {inv['n_plays']:,} rows | "
            f"{inv['total_hours']:,.1f} h | "
            f"{inv['first_play']} → {inv['last_play']} | "
            f"skip {inv['skip_pct']}% | "
            f"2017 rows: {inv['plays_2017']}"
        )
        print(f"wrote {args.db}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
