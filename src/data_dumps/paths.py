"""Data directory layout. Override with DATA_DUMPS_ROOT in Docker."""

from __future__ import annotations

import os
from pathlib import Path


def data_root() -> Path:
    if root := os.environ.get("DATA_DUMPS_ROOT"):
        return Path(root)
    # Repo root: src/data_dumps/paths.py → parents[2]
    return Path(__file__).resolve().parents[2]


def warehouse_db() -> Path:
    if path := os.environ.get("DATA_DUMPS_WAREHOUSE"):
        return Path(path)
    return data_root() / "warehouse" / "catalog.duckdb"


def raw_dir(source: str) -> Path:
    return data_root() / "raw" / source


def inbox_dir() -> Path:
    return data_root() / "inbox"
