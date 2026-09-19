"""Per-source Compare / Correlations series descriptors.

Assembled into catalogs via :mod:`data_dumps.contributions`. Keep grain and
aggregation choices in the source modules — do not auto-discover warehouse
columns or import every module dynamically.
"""

from __future__ import annotations

from data_dumps.contribution_series.airbnb import AIRBNB_COMPARE, AIRBNB_CORRELATE
from data_dumps.contribution_series.amazon import AMAZON_COMPARE, AMAZON_CORRELATE
from data_dumps.contribution_series.browser import BROWSER_COMPARE, BROWSER_CORRELATE
from data_dumps.contribution_series.chatgpt import CHATGPT_COMPARE, CHATGPT_CORRELATE
from data_dumps.contribution_series.duolingo import DUOLINGO_COMPARE, DUOLINGO_CORRELATE
from data_dumps.contribution_series.google import GOOGLE_COMPARE, GOOGLE_CORRELATE
from data_dumps.contribution_series.linkedin import LINKEDIN_COMPARE, LINKEDIN_CORRELATE
from data_dumps.contribution_series.miband import MIBAND_COMPARE, MIBAND_CORRELATE
from data_dumps.contribution_series.ring import RING_COMPARE, RING_CORRELATE
from data_dumps.contribution_series.slack import SLACK_COMPARE, SLACK_CORRELATE
from data_dumps.contribution_series.sleep import SLEEP_COMPARE, SLEEP_CORRELATE
from data_dumps.contribution_series.spotify import SPOTIFY_COMPARE, SPOTIFY_CORRELATE
from data_dumps.contribution_series.telegram import TELEGRAM_COMPARE, TELEGRAM_CORRELATE
from data_dumps.contribution_series.thunderbird import (
    THUNDERBIRD_COMPARE,
    THUNDERBIRD_CORRELATE,
)
from data_dumps.contribution_series.twitter import TWITTER_COMPARE, TWITTER_CORRELATE
from data_dumps.contribution_series.uber import UBER_COMPARE, UBER_CORRELATE

__all__ = [
    "SPOTIFY_COMPARE",
    "SPOTIFY_CORRELATE",
    "TELEGRAM_COMPARE",
    "TELEGRAM_CORRELATE",
    "TWITTER_COMPARE",
    "TWITTER_CORRELATE",
    "SLACK_COMPARE",
    "SLACK_CORRELATE",
    "LINKEDIN_COMPARE",
    "LINKEDIN_CORRELATE",
    "THUNDERBIRD_COMPARE",
    "THUNDERBIRD_CORRELATE",
    "SLEEP_COMPARE",
    "SLEEP_CORRELATE",
    "AMAZON_COMPARE",
    "AMAZON_CORRELATE",
    "MIBAND_COMPARE",
    "MIBAND_CORRELATE",
    "BROWSER_COMPARE",
    "BROWSER_CORRELATE",
    "RING_COMPARE",
    "RING_CORRELATE",
    "DUOLINGO_COMPARE",
    "DUOLINGO_CORRELATE",
    "UBER_COMPARE",
    "UBER_CORRELATE",
    "GOOGLE_COMPARE",
    "GOOGLE_CORRELATE",
    "AIRBNB_COMPARE",
    "AIRBNB_CORRELATE",
    "CHATGPT_COMPARE",
    "CHATGPT_CORRELATE",
]
