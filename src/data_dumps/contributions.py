"""Thin explicit contribution registry.

One append per dump: ingest Source + optional explorer gate/bounds + Compare /
Correlations series descriptors. No dynamic module discovery, no entry points.

``ingest.SOURCES`` and Compare/Correlations catalogs are derived from
``CONTRIBUTIONS``. Explorer panel imports stay lazy (notebooks import panels
directly) so ``uv run ingest`` does not pull Marimo/Plotly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import duckdb

from data_dumps import airbnb_queries as abq
from data_dumps import amazon_queries as amzq
from data_dumps import browser_queries as brq
from data_dumps import chatgpt_queries as cgq
from data_dumps import duolingo_queries as duoq
from data_dumps import google_queries as gq
from data_dumps import linkedin_queries as liq
from data_dumps import miband_queries as mbq
from data_dumps import ring_queries as ringq
from data_dumps import slack_queries as skq
from data_dumps import sleep_queries as slq
from data_dumps import spotify_queries as spq
from data_dumps import telegram_queries as tgq
from data_dumps import thunderbird_queries as tbq
from data_dumps import twitter_queries as twq
from data_dumps import uber_queries as ubq
from data_dumps.contribution_series import (
    AIRBNB_COMPARE,
    AIRBNB_CORRELATE,
    AMAZON_COMPARE,
    AMAZON_CORRELATE,
    BROWSER_COMPARE,
    BROWSER_CORRELATE,
    CHATGPT_COMPARE,
    CHATGPT_CORRELATE,
    DUOLINGO_COMPARE,
    DUOLINGO_CORRELATE,
    GOOGLE_COMPARE,
    GOOGLE_CORRELATE,
    LINKEDIN_COMPARE,
    LINKEDIN_CORRELATE,
    MIBAND_COMPARE,
    MIBAND_CORRELATE,
    RING_COMPARE,
    RING_CORRELATE,
    SLACK_COMPARE,
    SLACK_CORRELATE,
    SLEEP_COMPARE,
    SLEEP_CORRELATE,
    SPOTIFY_COMPARE,
    SPOTIFY_CORRELATE,
    TELEGRAM_COMPARE,
    TELEGRAM_CORRELATE,
    THUNDERBIRD_COMPARE,
    THUNDERBIRD_CORRELATE,
    TWITTER_COMPARE,
    TWITTER_CORRELATE,
    UBER_COMPARE,
    UBER_CORRELATE,
)
from data_dumps.series_catalog import MetricSpec, SeriesSpec
from data_dumps.sources.airbnb import AirbnbSource
from data_dumps.sources.amazon import AmazonSource
from data_dumps.sources.base import Source
from data_dumps.sources.browser import BrowserSource
from data_dumps.sources.chatgpt import ChatGPTSource
from data_dumps.sources.duolingo import DuolingoSource
from data_dumps.sources.google import GoogleSource
from data_dumps.sources.linkedin import LinkedInSource
from data_dumps.sources.miband import MiBandSource
from data_dumps.sources.ring import RingSource
from data_dumps.sources.slack import SlackSource
from data_dumps.sources.sleep import SleepSource
from data_dumps.sources.spotify import SpotifySource
from data_dumps.sources.spotify_account import SpotifyAccountSource
from data_dumps.sources.telegram import TelegramSource
from data_dumps.sources.thunderbird import ThunderbirdSource
from data_dumps.sources.twitter import TwitterSource
from data_dumps.sources.uber import UberSource

BoundsFn = Callable[[duckdb.DuckDBPyConnection], dict[str, Any]]


@dataclass(frozen=True)
class Contribution:
    """One platform dump (or Source-only sibling like Spotify Account Data)."""

    slug: str
    source: Source | None = None
    tab_label: str | None = None
    #: Iconify id for the explorer tab (e.g. ``lucide:music``). Rendered via ``mo.icon``.
    tab_icon: str | None = None
    gate_table: tuple[str, str] | None = None
    data_bounds: BoundsFn | None = None
    compare_series: tuple[SeriesSpec, ...] = field(default_factory=tuple)
    correlate_metrics: tuple[MetricSpec, ...] = field(default_factory=tuple)


# Cross-cutting explorer tabs (not tied to a Contribution).
HOME_TAB_LABEL = "Home"
HOME_TAB_ICON = "lucide:house"
COMPARE_TAB_LABEL = "Compare"
COMPARE_TAB_ICON = "lucide:columns-2"
CORRELATE_TAB_LABEL = "Correlations"
CORRELATE_TAB_ICON = "lucide:git-compare"


# Detect order matters when loaders could overlap — keep comments next to entries.
CONTRIBUTIONS: tuple[Contribution, ...] = (
    Contribution(
        slug="spotify",
        source=SpotifySource(),
        tab_label="Spotify",
        tab_icon="lucide:music",
        gate_table=("spotify", "plays"),
        data_bounds=spq.data_bounds,
        compare_series=SPOTIFY_COMPARE,
        correlate_metrics=SPOTIFY_CORRELATE,
    ),
    # Additive Account Data tables; no separate explorer tab.
    Contribution(
        slug="spotify_account",
        source=SpotifyAccountSource(),
    ),
    Contribution(
        slug="telegram",
        source=TelegramSource(),
        tab_label="Telegram",
        tab_icon="lucide:send",
        gate_table=("telegram", "messages"),
        data_bounds=tgq.data_bounds,
        compare_series=TELEGRAM_COMPARE,
        correlate_metrics=TELEGRAM_CORRELATE,
    ),
    Contribution(
        slug="linkedin",
        source=LinkedInSource(),
        tab_label="LinkedIn",
        tab_icon="lucide:briefcase",
        gate_table=("linkedin", "connections"),
        data_bounds=liq.data_bounds,
        compare_series=LINKEDIN_COMPARE,
        correlate_metrics=LINKEDIN_CORRELATE,
    ),
    Contribution(
        slug="twitter",
        source=TwitterSource(),
        tab_label="Twitter",
        tab_icon="lucide:bird",
        gate_table=("twitter", "tweets"),
        data_bounds=twq.data_bounds,
        compare_series=TWITTER_COMPARE,
        correlate_metrics=TWITTER_CORRELATE,
    ),
    Contribution(
        slug="slack",
        source=SlackSource(),
        tab_label="Slack",
        tab_icon="lucide:hash",
        gate_table=("slack", "messages"),
        data_bounds=skq.data_bounds,
        compare_series=SLACK_COMPARE,
        correlate_metrics=SLACK_CORRELATE,
    ),
    Contribution(
        slug="sleep",
        source=SleepSource(),
        tab_label="Sleep",
        tab_icon="lucide:moon",
        gate_table=("sleep", "sessions"),
        data_bounds=slq.data_bounds,
        compare_series=SLEEP_COMPARE,
        correlate_metrics=SLEEP_CORRELATE,
    ),
    Contribution(
        slug="miband",
        source=MiBandSource(),
        tab_label="Mi Band",
        tab_icon="lucide:heart-pulse",
        gate_table=("miband", "heart_rate"),
        data_bounds=mbq.data_bounds,
        compare_series=MIBAND_COMPARE,
        correlate_metrics=MIBAND_CORRELATE,
    ),
    Contribution(
        slug="browser",
        source=BrowserSource(),
        tab_label="Browser",
        tab_icon="lucide:globe",
        gate_table=("browser", "pages"),
        data_bounds=brq.data_bounds,
        compare_series=BROWSER_COMPARE,
        correlate_metrics=BROWSER_CORRELATE,
    ),
    Contribution(
        slug="thunderbird",
        source=ThunderbirdSource(),
        tab_label="Thunderbird",
        tab_icon="lucide:mail",
        gate_table=("thunderbird", "messages"),
        data_bounds=tbq.data_bounds,
        compare_series=THUNDERBIRD_COMPARE,
        correlate_metrics=THUNDERBIRD_CORRELATE,
    ),
    Contribution(
        slug="ring",
        source=RingSource(),
        tab_label="Ring",
        tab_icon="lucide:bell",
        gate_table=("ring", "device_events"),
        data_bounds=ringq.data_bounds,
        compare_series=RING_COMPARE,
        correlate_metrics=RING_CORRELATE,
    ),
    Contribution(
        slug="amazon",
        source=AmazonSource(),
        tab_label="Amazon",
        tab_icon="lucide:package",
        gate_table=("amazon", "order_items"),
        data_bounds=amzq.data_bounds,
        compare_series=AMAZON_COMPARE,
        correlate_metrics=AMAZON_CORRELATE,
    ),
    Contribution(
        slug="duolingo",
        source=DuolingoSource(),
        tab_label="Duolingo",
        tab_icon="lucide:languages",
        gate_table=("duolingo", "progress_events"),
        data_bounds=duoq.data_bounds,
        compare_series=DUOLINGO_COMPARE,
        correlate_metrics=DUOLINGO_CORRELATE,
    ),
    Contribution(
        slug="uber",
        source=UberSource(),
        tab_label="Uber",
        tab_icon="lucide:car",
        gate_table=("uber", "trips"),
        data_bounds=ubq.data_bounds,
        compare_series=UBER_COMPARE,
        correlate_metrics=UBER_CORRELATE,
    ),
    Contribution(
        slug="google",
        source=GoogleSource(),
        tab_label="Google",
        tab_icon="lucide:chrome",
        gate_table=("google", "calendar_events"),
        data_bounds=gq.data_bounds,
        compare_series=GOOGLE_COMPARE,
        correlate_metrics=GOOGLE_CORRELATE,
    ),
    Contribution(
        slug="airbnb",
        source=AirbnbSource(),
        tab_label="Airbnb",
        tab_icon="lucide:home",
        gate_table=("airbnb", "reservations"),
        data_bounds=abq.data_bounds,
        compare_series=AIRBNB_COMPARE,
        correlate_metrics=AIRBNB_CORRELATE,
    ),
    Contribution(
        slug="chatgpt",
        source=ChatGPTSource(),
        tab_label="ChatGPT",
        tab_icon="lucide:bot",
        gate_table=("chatgpt", "messages"),
        data_bounds=cgq.data_bounds,
        compare_series=CHATGPT_COMPARE,
        correlate_metrics=CHATGPT_CORRELATE,
    ),
)

SOURCES: list[Source] = [c.source for c in CONTRIBUTIONS if c.source is not None]

COMPARE_SERIES: tuple[SeriesSpec, ...] = tuple(
    s for c in CONTRIBUTIONS for s in c.compare_series
)
CORRELATE_METRICS: tuple[MetricSpec, ...] = tuple(
    m for c in CONTRIBUTIONS for m in c.correlate_metrics
)


def contribution_by_slug(slug: str) -> Contribution | None:
    for c in CONTRIBUTIONS:
        if c.slug == slug:
            return c
    return None


def explorer_contributions() -> list[Contribution]:
    """Platform tabs (excludes Source-only siblings without a tab label)."""
    return [c for c in CONTRIBUTIONS if c.tab_label and c.gate_table]


def bounds_fns_for_series() -> list[tuple[str, BoundsFn]]:
    """Unique (slug, data_bounds) for sources that expose Compare/Correlate series."""
    seen: set[str] = set()
    out: list[tuple[str, BoundsFn]] = []
    for c in CONTRIBUTIONS:
        if c.data_bounds is None:
            continue
        if not c.compare_series and not c.correlate_metrics:
            continue
        if c.slug in seen:
            continue
        # Map series.source field (platform) — use first series source or slug.
        source_key = (
            c.compare_series[0].source
            if c.compare_series
            else (c.correlate_metrics[0].source if c.correlate_metrics else c.slug)
        )
        if source_key in seen:
            continue
        seen.add(source_key)
        out.append((source_key, c.data_bounds))
    return out
