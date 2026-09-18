"""Render frequency tables as word-cloud PNGs.

No spaCy. Callers pass already-aggregated term counts.
"""

from __future__ import annotations

import io
from collections.abc import Mapping

import pandas as pd


def frequencies_from_frame(
    df: pd.DataFrame,
    *,
    term_col: str = "term",
    value_col: str = "n",
) -> dict[str, float]:
    if df.empty or term_col not in df.columns or value_col not in df.columns:
        return {}
    out: dict[str, float] = {}
    for term, value in zip(df[term_col], df[value_col], strict=True):
        if term is None or value is None:
            continue
        weight = float(value)
        if weight <= 0:
            continue
        out[str(term)] = weight
    return out


def wordcloud_png(freq: Mapping[str, float]) -> bytes | None:
    """PNG bytes, or None when there is nothing to draw."""
    cleaned = {str(term): float(weight) for term, weight in freq.items() if weight > 0}
    if not cleaned:
        return None
    from wordcloud import WordCloud

    cloud = WordCloud(
        width=900,
        height=420,
        background_color="white",
        collocations=False,
        max_words=min(150, len(cleaned)),
        prefer_horizontal=0.9,
    )
    cloud.generate_from_frequencies(cleaned)
    buf = io.BytesIO()
    cloud.to_image().save(buf, format="PNG")
    payload = buf.getvalue()
    return payload or None
