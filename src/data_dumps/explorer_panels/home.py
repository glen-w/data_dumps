"""Explorer homepage: description, warehouse totals, per-source span."""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_dumps.overview_queries import WarehouseOverview, sources_frame


def render_home_hero(mo: Any, overview: WarehouseOverview) -> Any:
    """Description and headline stats. Shown above the tab chips."""
    if overview.n_years is None:
        year_value = "—"
        year_caption = "no dated rows"
    else:
        year_value = f"{overview.min_year} → {overview.max_year}"
        noun = "year" if overview.n_years == 1 else "years"
        year_caption = f"{overview.n_years} calendar {noun}"
    if overview.first_day is not None and overview.last_day is not None:
        date_value = (
            f"{overview.first_day.isoformat()} → {overview.last_day.isoformat()}"
        )
    else:
        date_value = "—"

    intro = (
        "Personal GDPR and app exports, kept in one local DuckDB file. "
        "Source tabs are the dumps already ingested. "
        "**Compare** and **Correlations** look across them."
    )
    if overview.n_sources == 0:
        intro += (
            " Nothing is loaded yet. Stop this notebook, then "
            "`uv run ingest` a zip or export folder."
        )
    table_noun = "table" if overview.n_tables == 1 else "tables"
    return mo.vstack(
        [
            mo.md(f"## Warehouse\n\n{intro}"),
            mo.hstack(
                [
                    mo.stat(
                        value=f"{overview.n_sources:,}",
                        label="Sources",
                        caption="ingested",
                        bordered=True,
                    ),
                    mo.stat(
                        value=f"{overview.n_rows:,}",
                        label="Rows",
                        caption=f"across {overview.n_tables:,} {table_noun}",
                        bordered=True,
                    ),
                    mo.stat(
                        value=year_value,
                        label="Years",
                        caption=year_caption,
                        bordered=True,
                    ),
                    mo.stat(
                        value=date_value,
                        label="Dates",
                        caption="earliest → latest activity",
                        bordered=True,
                    ),
                ],
                justify="start",
                gap=1,
                wrap=True,
            ),
        ],
        gap=0.75,
    )


def render_home_panel(*, mo: Any, px: Any, overview: WarehouseOverview) -> Any:
    """Per-source row totals and year span. Shown under the tab chips."""
    if overview.n_sources == 0:
        return mo.md("_No source tables in the warehouse yet._")

    frame = sources_frame(overview)
    charts = _charts(mo, px, overview)
    blocks: list[Any] = [mo.md("### By source")]
    if charts is not None:
        blocks.append(charts)
    blocks.append(mo.ui.table(frame, selection=None, page_size=20))
    return mo.vstack(blocks, gap=1)


def _charts(mo: Any, px: Any, overview: WarehouseOverview) -> Any | None:
    figs: list[Any] = []
    rows_fig = _rows_chart(px, overview)
    if rows_fig is not None:
        figs.append(mo.ui.plotly(rows_fig))
    years_fig = _years_chart(px, overview)
    if years_fig is not None:
        figs.append(mo.ui.plotly(years_fig))
    if not figs:
        return None
    if len(figs) == 1:
        return figs[0]
    return mo.hstack(figs, widths="equal", gap=1, align="start")


def _rows_chart(px: Any, overview: WarehouseOverview) -> Any | None:
    plot = [s for s in overview.sources if s.rows > 0]
    if not plot:
        return None
    df = pd.DataFrame(
        {"source": [s.label for s in plot], "rows": [s.rows for s in plot]}
    )
    title = "Rows by source"
    if len(df) >= 2 and int(df["rows"].min()) > 0:
        if int(df["rows"].max()) / int(df["rows"].min()) >= 100:
            title = "Rows by source (log scale)"
    fig = px.bar(df, x="rows", y="source", orientation="h", title=title)
    fig.update_layout(
        yaxis={"categoryorder": "total ascending"},
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
        height=max(320, 36 * len(df)),
    )
    if title.endswith("(log scale)"):
        fig.update_xaxes(type="log")
    return fig


def _years_chart(px: Any, overview: WarehouseOverview) -> Any | None:
    dated = [
        s for s in overview.sources if s.min_year is not None and s.max_year is not None
    ]
    if not dated:
        return None
    labels: list[str] = []
    min_years: list[int] = []
    spans: list[int] = []
    for source in dated:
        assert source.min_year is not None and source.max_year is not None
        labels.append(source.label)
        min_years.append(source.min_year)
        spans.append(source.max_year - source.min_year + 1)
    df = pd.DataFrame(
        {"source": labels, "min_year": min_years, "span": spans}
    ).sort_values(["min_year", "source"], ascending=[True, True])
    fig = px.bar(
        df,
        x="span",
        y="source",
        base="min_year",
        orientation="h",
        title="Years covered",
    )
    order = df["source"].tolist()
    fig.update_layout(
        yaxis={
            "categoryorder": "array",
            "categoryarray": list(reversed(order)),
            "title": "",
        },
        xaxis={"title": ""},
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
        height=max(320, 36 * len(df)),
    )
    return fig
