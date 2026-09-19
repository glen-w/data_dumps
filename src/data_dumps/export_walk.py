"""Shared zip and folder walking for the Tools indexes.

Email and IP inventories both read original exports. Extractors stay in those
modules. This file only opens archives and strips YTD assignments.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

_MAX_MEMBER = 20 * 1024 * 1024
_YTD_RE = re.compile(r"^window\.YTD\.[^=]+=\s*", re.MULTILINE)


def basename(name: str) -> str:
    return Path(name).name.lower()


def newest(paths: list[Path], prefer: str | None = None) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if prefer:
        preferred = [path for path in existing if prefer in path.name.lower()]
        if preferred:
            existing = preferred
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def zip_hits(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted([*folder.glob("*.zip"), *folder.glob("*.zip.zip")])


def parse_ytd(data: bytes) -> Any:
    """Parse a ``window.YTD.*.partN = ...`` assignment. The prefix is stripped."""
    text = data.decode("utf-8", errors="replace")
    body = _YTD_RE.sub("", text, count=1).strip()
    if body.endswith(";"):
        body = body[:-1].strip()
    return json.loads(body)


def _is_zip(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".zip") or name.endswith(".zip.zip")


def iter_members(
    path: Path,
    member_ok: Callable[[str], bool],
    loose_globs: tuple[str, ...] = (),
) -> Iterator[tuple[str, bytes]]:
    """Yield ``(relative name, bytes)`` from a zip, a folder of zips, or loose files."""
    path = path.resolve()
    if not path.exists():
        return
    if path.is_file():
        if _is_zip(path):
            yield from _iter_zip(path, member_ok)
            return
        rel = path.name
        if member_ok(rel) and path.stat().st_size <= _MAX_MEMBER:
            yield rel, path.read_bytes()
        return
    zips = sorted(
        child for child in path.iterdir() if child.is_file() and _is_zip(child)
    )
    if zips:
        for archive in zips:
            yield from _iter_zip(archive, member_ok)
        return
    for pattern in loose_globs:
        for child in path.glob(pattern):
            if not child.is_file():
                continue
            rel = child.relative_to(path).as_posix()
            if not member_ok(rel) or child.stat().st_size > _MAX_MEMBER:
                continue
            yield rel, child.read_bytes()


def _iter_zip(
    path: Path, member_ok: Callable[[str], bool]
) -> Iterator[tuple[str, bytes]]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if not member_ok(name) or info.file_size > _MAX_MEMBER:
                continue
            yield name, archive.read(info)
