"""UI builders for the combined Marimo explorer tabs.

Public API is stable: ``from data_dumps.explorer_panels import make_*_controls,
render_*_panel``.
"""

from __future__ import annotations

from data_dumps.explorer_panels.airbnb import (
    AirbnbControls,
    make_airbnb_controls,
    render_airbnb_panel,
)
from data_dumps.explorer_panels.amazon import (
    AmazonControls,
    make_amazon_controls,
    render_amazon_panel,
)
from data_dumps.explorer_panels.browser import (
    BrowserControls,
    make_browser_controls,
    render_browser_panel,
)
from data_dumps.explorer_panels.chatgpt import (
    ChatGPTControls,
    make_chatgpt_controls,
    render_chatgpt_panel,
)
from data_dumps.explorer_panels.compare import (
    CompareControls,
    make_compare_controls,
    render_compare_panel,
)
from data_dumps.explorer_panels.correlate import (
    CorrelateControls,
    make_correlate_controls,
    render_correlate_panel,
)
from data_dumps.explorer_panels.duolingo import (
    DuolingoControls,
    make_duolingo_controls,
    render_duolingo_panel,
)
from data_dumps.explorer_panels.google import (
    GoogleControls,
    make_google_controls,
    render_google_panel,
)
from data_dumps.explorer_panels.linkedin import (
    LinkedInControls,
    make_linkedin_controls,
    render_linkedin_panel,
)
from data_dumps.explorer_panels.miband import (
    MiBandControls,
    make_miband_controls,
    render_miband_panel,
)
from data_dumps.explorer_panels.ring import (
    RingControls,
    make_ring_controls,
    render_ring_panel,
)
from data_dumps.explorer_panels.slack import (
    SlackControls,
    make_slack_controls,
    render_slack_panel,
)
from data_dumps.explorer_panels.sleep import (
    SleepControls,
    make_sleep_controls,
    render_sleep_panel,
)
from data_dumps.explorer_panels.spotify import (
    SpotifyControls,
    make_spotify_controls,
    render_spotify_panel,
)
from data_dumps.explorer_panels.telegram import (
    TelegramControls,
    make_telegram_controls,
    render_telegram_panel,
)
from data_dumps.explorer_panels.thunderbird import (
    ThunderbirdControls,
    make_thunderbird_controls,
    render_thunderbird_panel,
)
from data_dumps.explorer_panels.twitter import (
    TwitterControls,
    make_twitter_controls,
    render_twitter_panel,
)
from data_dumps.explorer_panels.uber import (
    UberControls,
    make_uber_controls,
    render_uber_panel,
)

__all__ = [
    "AirbnbControls",
    "AmazonControls",
    "BrowserControls",
    "ChatGPTControls",
    "CompareControls",
    "CorrelateControls",
    "DuolingoControls",
    "GoogleControls",
    "LinkedInControls",
    "MiBandControls",
    "RingControls",
    "SlackControls",
    "SleepControls",
    "SpotifyControls",
    "TelegramControls",
    "ThunderbirdControls",
    "TwitterControls",
    "UberControls",
    "make_airbnb_controls",
    "make_amazon_controls",
    "make_browser_controls",
    "make_chatgpt_controls",
    "make_compare_controls",
    "make_correlate_controls",
    "make_duolingo_controls",
    "make_google_controls",
    "make_linkedin_controls",
    "make_miband_controls",
    "make_ring_controls",
    "make_slack_controls",
    "make_sleep_controls",
    "make_spotify_controls",
    "make_telegram_controls",
    "make_thunderbird_controls",
    "make_twitter_controls",
    "make_uber_controls",
    "render_airbnb_panel",
    "render_amazon_panel",
    "render_browser_panel",
    "render_chatgpt_panel",
    "render_compare_panel",
    "render_correlate_panel",
    "render_duolingo_panel",
    "render_google_panel",
    "render_linkedin_panel",
    "render_miband_panel",
    "render_ring_panel",
    "render_slack_panel",
    "render_sleep_panel",
    "render_spotify_panel",
    "render_telegram_panel",
    "render_thunderbird_panel",
    "render_twitter_panel",
    "render_uber_panel",
]
