#!/usr/bin/env python3
"""CLI: ingest a GDPR dump zip into the local DuckDB warehouse."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

from data_dumps.paths import warehouse_db
from data_dumps.sources.base import Source
from data_dumps.sources.browser import BrowserSource
from data_dumps.sources.linkedin import LinkedInSource
from data_dumps.sources.miband import MiBandSource
from data_dumps.sources.slack import SlackSource
from data_dumps.sources.sleep import SleepSource
from data_dumps.sources.spotify import SpotifySource
from data_dumps.sources.spotify_account import SpotifyAccountSource
from data_dumps.sources.telegram import TelegramSource
from data_dumps.sources.thunderbird import ThunderbirdSource
from data_dumps.sources.twitter import TwitterSource

SOURCES: list[Source] = [
    SpotifySource(),
    SpotifyAccountSource(),
    TelegramSource(),
    LinkedInSource(),
    TwitterSource(),
    SlackSource(),
    SleepSource(),
    MiBandSource(),
    BrowserSource(),
    ThunderbirdSource(),
]


def pick_source(path: Path) -> Source | None:
    for source in SOURCES:
        if source.detect(path):
            return source
    return None


def main(argv: list[str] | None = None) -> int:
    db_default = warehouse_db()
    parser = argparse.ArgumentParser(description="Ingest a GDPR data dump into DuckDB")
    parser.add_argument("path", type=Path, help="Path to zip or extracted folder")
    parser.add_argument(
        "--db",
        type=Path,
        default=db_default,
        help=f"DuckDB catalog path (default: {db_default})",
    )
    parser.add_argument(
        "--identity",
        action="append",
        default=[],
        metavar="EMAIL",
        help=(
            "Thunderbird identity email for sent/received direction "
            "(repeatable; also DATA_DUMPS_TB_IDENTITIES=a,b)"
        ),
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

    if args.identity and isinstance(source, ThunderbirdSource):
        source.identities |= {e.strip().lower() for e in args.identity if e.strip()}

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(args.db))
    try:
        print(f"loading {path.name} via {source.name}…")
        source.load(path, conn)
        inv = source.inventory(conn)
        print(inv["summary"])
        print(f"wrote {args.db}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
