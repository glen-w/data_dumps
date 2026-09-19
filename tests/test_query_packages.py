"""Contracts for query packages split from monolithic modules."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import data_dumps


def test_query_packages_are_packages_not_shadowed_modules():
    root = Path(data_dumps.__file__).resolve().parent
    for name in (
        "slack_queries",
        "amazon_queries",
        "spotify_queries",
        "google_queries",
        "chatgpt_queries",
    ):
        assert (root / name / "__init__.py").is_file()
        assert not (root / f"{name}.py").exists()
        mod = importlib.import_module(f"data_dumps.{name}")
        assert Path(mod.__file__).name == "__init__.py"


def test_stable_public_reexports():
    from data_dumps import amazon_queries as amzq
    from data_dumps import chatgpt_queries as cgq
    from data_dumps import google_queries as gq
    from data_dumps import slack_queries as skq
    from data_dumps import spotify_queries as spq

    for attr in (
        "FilterState",
        "data_bounds",
        "filter_from_widgets",
        "scoreboard",
        "person_scoreboard",
        "circadian_heatmap",
    ):
        assert callable(getattr(skq, attr)) or hasattr(skq, attr)

    for attr in (
        "FilterState",
        "data_bounds",
        "scoreboard",
        "alexa_scoreboard",
        "audible_hours",
        "_year_clause",
    ):
        assert hasattr(amzq, attr)

    for attr in (
        "FilterState",
        "data_bounds",
        "scoreboard",
        "library_counts",
        "narrative_context",
        "_where_and_params",
        "circadian_heatmap",
        "late_hours_daily",
    ):
        assert hasattr(spq, attr)

    for attr in (
        "FilterState",
        "data_bounds",
        "filter_from_widgets",
        "scoreboard",
        "surfaces_monthly",
        "duration_vs_hour_scatter",
        "maps_saves_monthly_total",
        "play_installs_monthly_total",
    ):
        assert hasattr(gq, attr)

    for attr in (
        "FilterState",
        "data_bounds",
        "scoreboard",
        "narrative_context",
        "NARRATIVE_CONTEXT_KEYS",
        "message_tokens",
    ):
        assert hasattr(cgq, attr)


def test_no_three_arg_has_table_passthroughs():
    """spotify / miband / sleep must not wrap query_util.has_table(conn, schema, table)."""
    import data_dumps.miband_queries as mbq
    import data_dumps.sleep_queries as slq
    import data_dumps.spotify_queries as spq

    for mod in (spq, mbq, slq):
        assert not hasattr(mod, "has_table"), f"{mod.__name__} still exports has_table"


def test_browser_panel_has_no_narrate_di_param():
    from data_dumps.explorer_panels.browser import render_browser_panel

    params = inspect.signature(render_browser_panel).parameters
    assert "narrate" not in params
