"""Load the one explicit user contribution file.

``$DATA_DUMPS_ROOT/user_contributions.py`` may export ``CONTRIBUTIONS``.
That path is imported by name. This is not entry points, and it does not
scan a directory of modules. A missing file is an empty tuple.

The file runs as the user who owns the data root. Do not import Marimo at
module level — ``uv run ingest`` must stay free of it. Panel callables may
import Marimo inside the function.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from data_dumps.contributions import CONTRIBUTIONS, Contribution
from data_dumps.paths import data_root

USER_FILE = "user_contributions.py"
_LOADING = False


def user_contributions_path() -> Path:
    return data_root() / USER_FILE


def load_user_contributions() -> tuple[Contribution, ...]:
    global _LOADING
    path = user_contributions_path()
    if not path.is_file() or _LOADING:
        return ()
    _LOADING = True
    try:
        return _load_file(path)
    finally:
        _LOADING = False


def _load_file(path: Path) -> tuple[Contribution, ...]:
    spec = importlib.util.spec_from_file_location("data_dumps_user_contributions", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    raw = getattr(module, "CONTRIBUTIONS", None)
    if raw is None:
        raise RuntimeError(f"{path} must define CONTRIBUTIONS")
    if isinstance(raw, Contribution):
        items: tuple[Contribution, ...] = (raw,)
    else:
        try:
            items = tuple(raw)
        except TypeError as exc:
            raise RuntimeError(f"{path} CONTRIBUTIONS must be a sequence") from exc
    _validate(path, items)
    return items


def _validate(path: Path, items: tuple[Contribution, ...]) -> None:
    builtin_slugs = {item.slug for item in CONTRIBUTIONS}
    builtin_compare = {
        spec.id for item in CONTRIBUTIONS for spec in item.compare_series
    }
    builtin_corr = {
        spec.id for item in CONTRIBUTIONS for spec in item.correlate_metrics
    }
    seen = set(builtin_slugs)
    seen_compare = set(builtin_compare)
    seen_corr = set(builtin_corr)
    for item in items:
        if not isinstance(item, Contribution):
            raise RuntimeError(
                f"{path} CONTRIBUTIONS entries must be Contribution instances"
            )
        if item.slug in seen:
            raise RuntimeError(
                f"{path} slug {item.slug!r} collides with a built-in or earlier plug-in"
            )
        seen.add(item.slug)
        for series in item.compare_series:
            if series.id in seen_compare:
                raise RuntimeError(
                    f"{path} compare series id {series.id!r} is already used"
                )
            seen_compare.add(series.id)
        for metric in item.correlate_metrics:
            if metric.id in seen_corr:
                raise RuntimeError(
                    f"{path} correlate metric id {metric.id!r} is already used"
                )
            seen_corr.add(metric.id)
