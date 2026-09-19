# Security

This is a **local** ingest and dashboard tool. It is not a hosted service. Exports and `catalog.duckdb` stay on the machine that runs it.

## What to keep private

Do not commit dumps, extracted files, DuckDB warehouses, or `.env`. Those paths are listed in `.gitignore`. Do not attach real exports to issues or pull requests.

The Marimo dashboard has no password. Bind it to `127.0.0.1` only (Docker Compose already does). Do not publish it on a shared or public network.

Ingest is built around **untrusted zip/folder layouts** from third-party exports. Treat a dump you did not request yourself as untrusted input.

## Reporting a vulnerability

Please **do not** open a public issue for:

- Ways to leak warehouse contents if the dashboard is exposed beyond loopback
- Parser bugs that could execute or exfiltrate data from a malicious archive
- Anything that would publish someone else’s GDPR export

Use GitHub’s **private vulnerability reporting** (Security → Advisories) on this repository. If the repo host has no advisory flow, email the maintainer listed in `LICENSE` / git history.

We will acknowledge the report and say whether a fix is coming.
