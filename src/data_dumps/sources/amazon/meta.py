"""Shared typing hooks for Amazon frame-builder mixins."""

from __future__ import annotations

from typing import Any


class AmazonMetaMixin:
    """Declares ``_meta`` for mypy; ``AmazonSource`` provides the real implementation."""

    def _meta(
        self,
        meta: list[dict[str, Any]],
        logical: str,
        source: str | None,
        raw_n: int,
        kept: int,
        note: str = "",
    ) -> None:
        raise NotImplementedError
