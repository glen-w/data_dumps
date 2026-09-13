"""Unit tests for shared explorer panel chart helpers."""

from __future__ import annotations

import pandas as pd
import plotly.express as px

from data_dumps.explorer_panels import charts as panel_charts

SUN_FIRST = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}


def test_circadian_heatmap_empty_uses_empty_title():
    fig = panel_charts.circadian_heatmap(
        px,
        pd.DataFrame(columns=["dow", "hour", "hours"]),
        z="hours",
        dow_labels=SUN_FIRST,
        title="Hours by weekday × hour (local)",
        empty_title="No circadian data for filter",
    )
    assert "No circadian data for filter" in fig.layout.title.text


def test_circadian_heatmap_hours_z_column():
    df = pd.DataFrame(
        {"dow": [1, 2], "hour": [9, 10], "hours": [1.5, 2.0]},
    )
    fig = panel_charts.circadian_heatmap(
        px,
        df,
        z="hours",
        dow_labels=SUN_FIRST,
        title="Hours by weekday × hour (local)",
        empty_title="No circadian data for filter",
    )
    assert "Hours by weekday × hour" in fig.layout.title.text


def test_normalized_overlay_empty():
    fig = panel_charts.normalized_overlay(
        px,
        pd.DataFrame(columns=["year_month", "pct_of_max", "series_label", "value", "unit"]),
        title="Monthly activity (% of each series' max)",
        empty_title="Select up to 6 series",
    )
    assert "Select up to 6 series" in fig.layout.title.text


def test_normalized_overlay_multi_series():
    df = pd.DataFrame(
        {
            "year_month": ["2020-01", "2020-02", "2020-01", "2020-02"],
            "series_label": ["A", "A", "B", "B"],
            "pct_of_max": [50.0, 100.0, 25.0, 100.0],
            "value": [1.0, 2.0, 10.0, 40.0],
            "unit": ["h", "h", "msg", "msg"],
        }
    )
    fig = panel_charts.normalized_overlay(
        px,
        df,
        title="Monthly activity (% of each series' max)",
        empty_title="empty",
    )
    assert "Monthly activity" in fig.layout.title.text
    assert fig.layout.yaxis.title.text == "% of series max"


def test_correlation_heatmap_empty_and_matrix():
    empty = panel_charts.correlation_heatmap(
        px, pd.DataFrame(), title="corr", empty_title="Need ≥2 series"
    )
    assert "Need ≥2 series" in empty.layout.title.text
    corr = pd.DataFrame(
        [[1.0, 0.5], [0.5, 1.0]],
        index=["A", "B"],
        columns=["A", "B"],
    )
    fig = panel_charts.correlation_heatmap(px, corr, title="Series shape correlation")
    assert "Series shape correlation" in fig.layout.title.text


def test_scatter_pair_lag_bars_zscore():
    scatter = pd.DataFrame(
        {
            "day": pd.date_range("2020-01-01", periods=5, freq="D"),
            "x": [1, 2, 3, 4, 5],
            "y": [2, 4, 6, 8, 10],
        }
    )
    fig_s = panel_charts.scatter_pair(px, scatter, title="Focus pair", x_title="X", y_title="Y")
    assert "Focus pair" in fig_s.layout.title.text

    lag = pd.DataFrame({"lag": [-1, 0, 1], "r": [0.2, 0.9, 0.1], "n": [40, 40, 40]})
    fig_l = panel_charts.lag_bars(px, lag, title="Lag scan")
    assert "Lag scan" in fig_l.layout.title.text

    zdf = pd.DataFrame(
        {
            "time_key": pd.date_range("2020-01-01", periods=4, freq="D"),
            "z": [0.0, 1.0, -1.0, 0.5],
            "metric_label": ["A"] * 4,
        }
    )
    fig_z = panel_charts.zscore_overlay(px, zdf, title="z overlay")
    assert "z overlay" in fig_z.layout.title.text
