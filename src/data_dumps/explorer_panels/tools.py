"""Tools tab: every email address, with where it came from."""

from __future__ import annotations

from typing import Any

import duckdb

from data_dumps.email_inventory import inventory_frame


def render_tools_panel(*, mo: Any, conn: duckdb.DuckDBPyConnection) -> Any:
    """Account, contact, and in-text addresses. Not shown on source tabs."""
    frame, note = inventory_frame(conn)
    n_rows = len(frame)
    n_addresses = int(frame["Email address"].nunique()) if n_rows else 0
    n_services = int(frame["Service"].nunique()) if n_rows else 0
    blocks = [
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
    return mo.vstack(blocks, gap=0.75)
