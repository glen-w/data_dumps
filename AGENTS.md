# Agent notes

Local tools to ingest and explore personal GDPR / app exports into DuckDB, then Marimo explorers. Dumps and the warehouse stay under `~/Documents/data_dumps_raw` (or `DATA_DUMPS_ROOT`) — **never git**.

Start from [README.md](README.md) and [docs/WAREHOUSE.md](docs/WAREHOUSE.md) (single-writer lock). Direction: [docs/ROADMAP.md](docs/ROADMAP.md). Dashboard depth bar: [assessments/dashboard-depth-2026-09.md](assessments/dashboard-depth-2026-09.md).

When **adding a new dump / Source / explorer tab**, follow [docs/guides/add-a-dump.md](docs/guides/add-a-dump.md) before writing loaders or panels. Companion rule: [`.cursor/rules/add-dump.mdc`](.cursor/rules/add-dump.mdc).

**Do not:** commit dumps or DuckDB; run ingest while Marimo holds the warehouse; load IPs/phones/ads/KYC into source tables (the Tools tab / `ip_inventory` lists login and access-log IPs from the exports the loaders skip — add an extractor there, not a column); put email addresses on source tables (the Tools tab / `email_inventory` lists them, including other people and in-text mentions); expand Mi Band; invent dynamic plugin discovery (use thin `CONTRIBUTIONS`); format `notebooks/` with Black/Ruff.
