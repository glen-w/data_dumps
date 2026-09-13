"""Shared Plotly chart builders for explorer panels."""

from __future__ import annotations

from typing import Any

import pandas as pd


def empty_heatmap(px: Any, title: str) -> Any:
    return px.density_heatmap(title=title)


def empty_line(px: Any, title: str) -> Any:
    return px.line(title=title)


def normalized_overlay(
    px: Any,
    df: pd.DataFrame,
    *,
    title: str,
    empty_title: str | None = None,
) -> Any:
    """Multi-series line chart with y = pct_of_max; hover shows raw value + unit."""
    if df.empty or "pct_of_max" not in df.columns:
        return empty_line(px, empty_title or title)
    fig = px.line(
        df,
        x="year_month",
        y="pct_of_max",
        color="series_label",
        title=title,
        custom_data=["value", "unit"] if {"value", "unit"} <= set(df.columns) else None,
    )
    fig.update_layout(
        xaxis_title="Month",
        yaxis_title="% of series max",
        legend_title_text="Series",
        yaxis={"range": [0, 105]},
    )
    if {"value", "unit"} <= set(df.columns):
        fig.update_traces(
            hovertemplate=(
                "%{fullData.name}<br>"
                "%{x}: %{y:.1f}% of max"
                "<br>raw=%{customdata[0]} %{customdata[1]}"
                "<extra></extra>"
            )
        )
    return fig


def correlation_heatmap(
    px: Any,
    corr: pd.DataFrame,
    *,
    title: str,
    empty_title: str | None = None,
) -> Any:
    """Pearson correlation matrix as a diverging heatmap (NaN → blank)."""
    if corr is None or corr.empty:
        return empty_heatmap(px, empty_title or title)
    z = corr.astype(float)
    fig = px.imshow(
        z,
        x=list(z.columns),
        y=list(z.index),
        color_continuous_scale="RdBu",
        zmin=-1,
        zmax=1,
        title=title,
        aspect="auto",
        labels={"color": "r"},
    )
    fig.update_layout(
        xaxis_title="",
        yaxis_title="",
        xaxis={"side": "bottom"},
    )
    fig.update_traces(
        hovertemplate="%{y} × %{x}<br>r=%{z:.2f}<extra></extra>",
    )
    return fig


# Plan alias.
corr_heatmap = correlation_heatmap


def scatter_pair(
    px: Any,
    df: pd.DataFrame,
    *,
    title: str,
    x_title: str = "x",
    y_title: str = "y",
    empty_title: str | None = None,
) -> Any:
    """Raw-units scatter for a focus pair (columns day, x, y)."""
    if df.empty or not {"x", "y"} <= set(df.columns):
        return px.scatter(title=empty_title or title)
    fig = px.scatter(
        df,
        x="x",
        y="y",
        title=title,
        hover_data=["day"] if "day" in df.columns else None,
    )
    fig.update_layout(xaxis_title=x_title, yaxis_title=y_title)
    return fig


def lag_bars(
    px: Any,
    lag_df: pd.DataFrame,
    *,
    title: str,
    empty_title: str | None = None,
) -> Any:
    """Bar chart of Pearson r vs lag."""
    if lag_df.empty or "lag" not in lag_df.columns:
        return px.bar(title=empty_title or title)
    plot = lag_df.dropna(subset=["r"]).copy() if "r" in lag_df.columns else lag_df
    if plot.empty:
        return px.bar(title=empty_title or title)
    fig = px.bar(plot, x="lag", y="r", title=title)
    fig.update_layout(xaxis_title="Lag (B relative to A)", yaxis_title="Pearson r")
    fig.update_yaxes(range=[-1.05, 1.05])
    return fig


def zscore_overlay(
    px: Any,
    df: pd.DataFrame,
    *,
    title: str,
    empty_title: str | None = None,
) -> Any:
    """Multi-series line of per-metric z-scores (columns time_key, z, metric_label)."""
    if df.empty or "z" not in df.columns:
        return empty_line(px, empty_title or title)
    fig = px.line(
        df,
        x="time_key",
        y="z",
        color="metric_label",
        title=title,
    )
    fig.update_layout(
        xaxis_title="Time",
        yaxis_title="z-score",
        legend_title_text="Metric",
    )
    return fig


def circadian_heatmap(
    px: Any,
    df: pd.DataFrame,
    *,
    z: str,
    dow_labels: dict[int, str],
    title: str,
    colorscale: str = "Viridis",
    empty_title: str | None = None,
    xaxis_title: str = "Hour",
    yaxis_title: str = "Weekday",
    histfunc: str | None = None,
    ordered_dow: bool = False,
    layout_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Weekday × hour density heatmap with optional empty stub."""
    if df.empty:
        return empty_heatmap(px, empty_title or title)
    heat = df.copy()
    heat["dow_label"] = heat["dow"].map(dow_labels)
    kw: dict[str, Any] = {
        "x": "hour",
        "y": "dow_label",
        "z": z,
        "title": title,
        "color_continuous_scale": colorscale,
    }
    if histfunc is not None:
        kw["histfunc"] = histfunc
    if ordered_dow:
        kw["category_orders"] = {
            "dow_label": [dow_labels[i] for i in sorted(dow_labels)]
        }
    fig = px.density_heatmap(heat, **kw)
    layout: dict[str, Any] = {"xaxis_title": xaxis_title, "yaxis_title": yaxis_title}
    if layout_kwargs:
        layout.update(layout_kwargs)
    fig.update_layout(**layout)
    return fig


def iso_week_calendar(
    px: Any,
    df: pd.DataFrame,
    *,
    z: str,
    title: str,
    colorscale: str = "Blues",
    day_col: str = "day",
    empty_title: str | None = None,
    facet_by_year: bool = False,
    histfunc: str | None = None,
    xaxis_title: str | None = None,
    yaxis_title: str | None = None,
    reverse_y: bool = False,
    height_per_year: int | None = None,
) -> Any:
    """Daily activity as ISO-week calendar heatmap.

    ``facet_by_year=False`` → x=weekday, y=ISO week (Telegram/Sleep style).
    ``facet_by_year=True`` → x=week, y=weekday, facet_row=year (Slack/Browser style).
    """
    if df.empty:
        return empty_heatmap(px, empty_title or title)
    cal = df.copy()
    cal[day_col] = pd.to_datetime(cal[day_col], errors="coerce")
    cal = cal.dropna(subset=[day_col])
    if cal.empty:
        return empty_heatmap(px, empty_title or title)
    iso = cal[day_col].dt.isocalendar()
    cal["week"] = iso["week"].astype(int)
    cal["dow"] = cal[day_col].dt.dayofweek
    cal["year"] = iso["year"].astype(int)

    if facet_by_year:
        kw: dict[str, Any] = {
            "x": "week",
            "y": "dow",
            "z": z,
            "facet_row": "year",
            "title": title,
            "color_continuous_scale": colorscale,
        }
        if histfunc is not None:
            kw["histfunc"] = histfunc
        fig = px.density_heatmap(cal, **kw)
        if height_per_year is not None:
            fig.update_layout(height=max(320, height_per_year * cal["year"].nunique()))
        if reverse_y:
            fig.update_yaxes(matches=None, autorange="reversed", title="")
        fig.update_xaxes(title=xaxis_title or "ISO week")
        if yaxis_title is not None and not reverse_y:
            fig.update_layout(yaxis_title=yaxis_title)
        if facet_by_year:
            fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
        return fig

    kw = {
        "x": "dow",
        "y": "week",
        "z": z,
        "title": title,
        "color_continuous_scale": colorscale,
    }
    if histfunc is not None:
        kw["histfunc"] = histfunc
    fig = px.density_heatmap(cal, **kw)
    fig.update_layout(
        xaxis_title=xaxis_title or "Weekday (Mon=0)",
        yaxis_title=yaxis_title or "ISO week",
    )
    return fig
