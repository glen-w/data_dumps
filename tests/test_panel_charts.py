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
