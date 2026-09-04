"""Data directory layout.

Dumps, extracted JSON, and the DuckDB warehouse live outside the git repo
(default: ~/Documents/data_dumps_raw) so the image can bind-mount data only.
Override with DATA_DUMPS_ROOT (Docker sets this to /data).
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATA_ROOT = Path.home() / "Documents" / "data_dumps_raw"


def data_root() -> Path:
    if root := os.environ.get("DATA_DUMPS_ROOT"):
        return Path(root).expanduser()
    return DEFAULT_DATA_ROOT


def warehouse_db() -> Path:
    if path := os.environ.get("DATA_DUMPS_WAREHOUSE"):
        return Path(path).expanduser()
    return data_root() / "warehouse" / "catalog.duckdb"


def raw_dir(source: str) -> Path:
    return data_root() / "raw" / source


def inbox_dir() -> Path:
    return data_root() / "inbox"
