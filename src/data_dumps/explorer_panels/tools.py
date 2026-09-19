"""Tools tab: every email address and IP, with where each came from."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from data_dumps.email_inventory import inventory_frame
from data_dumps.explorer_panels.charts import geo_bubble_map
from data_dumps.ip_inventory import inventory_frame as ip_inventory_frame
from data_dumps.ip_inventory import map_frame


def _email_blocks(mo: Any, conn: duckdb.DuckDBPyConnection) -> list[Any]:
    frame, note = inventory_frame(conn)
    n_rows = len(frame)
    n_addresses = int(frame["Email address"].nunique()) if n_rows else 0
    n_services = int(frame["Service"].nunique()) if n_rows else 0
    blocks: list[Any] = [
        mo.md(
            "## Emails\n\n"
            "Your addresses and other people's, including ones that only appear "
            "inside a chat, a mail message, or a profile the source tabs leave out."
        ),
        mo.md(note),
        mo.hstack(
            [
                mo.stat(
                    value=f"{n_addresses:,}",
                    label="Addresses",
                    caption="unique",
                    bordered=True,
                ),
                mo.stat(
                    value=f"{n_rows:,}",
                    label="Rows",
                    caption="address × where it showed up",
                    bordered=True,
                ),
                mo.stat(
                    value=f"{n_services:,}",
                    label="Services",
                    caption="with at least one address",
                    bordered=True,
                ),
            ],
            justify="start",
            gap=1,
            wrap=True,
        ),
    ]
    if frame.empty:
        blocks.append(
            mo.md(
                "_Nothing found. Ingest an export, then open this tab again. "
                "The index is rebuilt when those files change._"
            )
        )
    else:
        blocks.append(mo.ui.table(frame, selection=None, page_size=50))
    return blocks


def _filled(series: pd.Series) -> int:
    text = series.fillna("").astype(str).str.strip()
    return int(text[text != ""].nunique())


def _ip_blocks(mo: Any, px: Any, conn: duckdb.DuckDBPyConnection) -> list[Any]:
    frame, note = ip_inventory_frame(conn)
    n_rows = len(frame)
    n_ips = int(frame["IP address"].nunique()) if n_rows else 0
    n_countries = _filled(frame["Country"]) if n_rows else 0
    n_isps = _filled(frame["ISP"]) if n_rows else 0
    blocks: list[Any] = [
        mo.md(
            "## IP addresses\n\n"
            "Logins, sessions, devices, and access logs the source tabs leave out, "
            "with city and network operator when a local GeoLite2 database is present."
        ),
        mo.md(note),
        mo.hstack(
            [
                mo.stat(
                    value=f"{n_ips:,}",
                    label="IP addresses",
                    caption="unique",
                    bordered=True,
                ),
                mo.stat(
                    value=f"{n_countries:,}",
                    label="Countries",
                    caption="from the lookup",
                    bordered=True,
                ),
                mo.stat(
                    value=f"{n_isps:,}",
                    label="ISPs",
                    caption="network operator",
                    bordered=True,
                ),
            ],
            justify="start",
            gap=1,
            wrap=True,
        ),
    ]
    if frame.empty:
        blocks.append(
            mo.md(
                "_Nothing found. Ingest an export that includes a login or access log, "
                "then open this tab again._"
            )
        )
        return blocks
    located = map_frame(frame)
    blocks.append(
        geo_bubble_map(
            px,
            located,
            size="Events",
            hover_name="Place",
            lat="Latitude",
            lon="Longitude",
            color="Country",
            title="Where those addresses were seen",
            empty_title="No located addresses yet",
        )
    )
    display = frame.drop(columns=["Latitude", "Longitude"])
    blocks.append(mo.ui.table(display, selection=None, page_size=50))
    return blocks


def render_tools_panel(*, mo: Any, px: Any, conn: duckdb.DuckDBPyConnection) -> Any:
    """Emails, then IP addresses. Not shown on source tabs."""
    blocks = _email_blocks(mo, conn)
    blocks.extend(_ip_blocks(mo, px, conn))
    return mo.vstack(blocks, gap=0.75)
