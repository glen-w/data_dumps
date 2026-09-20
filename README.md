<p align="center">
  <img src="assets/logo.png" alt="" width="160">
</p>

# data_dumps

Local tools to ingest your own GDPR and app exports into DuckDB, then explore them in a [Marimo](https://marimo.io) dashboard. This is not a hosted service. Dumps and the warehouse stay on your machine, outside the git tree.

Hosted landing: [glenwright.earth/data_dumps](https://glenwright.earth/data_dumps/) ([`website/`](website/)).

## Privacy

The dashboard has no password. Bind it to `127.0.0.1` (Docker Compose already publishes `127.0.0.1:2718`). Do not put it on a shared network.

Ingest drops IPs, phones, ads, and KYC from the source tables, and those dashboards do not show email addresses. The **Tools** tab lists every address it can find — yours and other people's, including ones only mentioned in chats or mail — and where each one came from. It also lists login, session, and access-log IP addresses from those same original exports, with city and ISP when GeoLite2 databases are in `warehouse/geoip/`. Those indexes are cached under the data root (`warehouse/email_inventory.json`, `warehouse/ip_inventory.json`), not in git, and they are not written into the source tables.

Do not commit dumps, extracted files, DuckDB databases, or `.env`. Those paths are already listed in [.gitignore](.gitignore). This git tree is code and synthetic tests only.

Vulnerability reports: [SECURITY.md](SECURITY.md).

Wall-clock charts use a hardcoded timezone, not your system zone. Most sources use `Europe/Rome`. Slack, Google, Airbnb, and ChatGPT use `Europe/Paris`. Ring uses `Europe/London`.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Optional: Docker, for the same ingest and dashboard without a local virtualenv

## Install and first ingest

Put exports under a data root. The default is `~/Documents/data_dumps_raw`. Override it with `DATA_DUMPS_ROOT`. The DuckDB file is `$DATA_DUMPS_ROOT/warehouse/catalog.duckdb` (or `DATA_DUMPS_WAREHOUSE`).

Spotify Extended Streaming History is the clearest first source. Request steps and the expected zip layout are in the [Spotify](docs/guides/services/spotify.md#extended-streaming-history) guide.

```bash
uv sync
uv run ingest /path/to/my_spotify_data.zip
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

Open `http://127.0.0.1:2718`. Use `marimo edit` only when you are changing notebook cells.

## Warehouse lock

`catalog.duckdb` is single-writer. The dashboard and `ingest` / `enrich-musicbrainz` cannot run at the same time, even though the notebook opens the file read-only. Stop Marimo, or run `docker compose stop app`, before ingesting or enriching. Full workflows: [docs/WAREHOUSE.md](docs/WAREHOUSE.md).

## Docker

The image contains code only. Compose bind-mounts `~/Documents/data_dumps_raw` at `/data` and sets `DATA_DUMPS_ROOT=/data`. Change that volume if your exports live elsewhere.

```bash
docker compose build
docker compose run --rm --entrypoint ingest app /data/spotify/my_spotify_data.zip
docker compose up app
```

Stop `app` before the next ingest. The published port is loopback-only.

## Other exports

Each loader detects its own zip or folder. The same `uv run ingest /path/to/export` command covers Telegram, LinkedIn, Slack, Google Takeout, and the rest. How to request each export, which files `detect()` accepts, and what is dropped: [docs/guides/getting-your-data.md](docs/guides/getting-your-data.md).

A source that is not in that list can still plug in. Put a `data_dumps.json` next to a CSV or JSON file and ingest that folder — the **Custom** tab charts it. A full loader and panel go in one file, `$DATA_DUMPS_ROOT/user_contributions.py`, not a scanned plugin directory. See [Custom](docs/guides/services/custom.md).

After more than one source is loaded, the explorer adds **Compare** and **Correlations** tabs. Those series are registered explicitly in `src/data_dumps/contributions.py`, not discovered from warehouse columns.

## Optional later

MusicBrainz genre and decade tags, and a local Ollama narrative that receives aggregates only, are in [docs/guides/getting-your-data.md](docs/guides/getting-your-data.md#optional-enrichment). Stop the dashboard first.

## Tests

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run black --check src tests
uv run mypy src
```

Do not run Black or Ruff on `notebooks/`. Marimo cell structure is not a formatter target.

## Contributing

New sources follow [docs/guides/add-a-dump.md](docs/guides/add-a-dump.md). Short version: [CONTRIBUTING.md](CONTRIBUTING.md).

---

<p align="center">
  <a href="https://ko-fi.com/C0C1XK8G" target="_blank" rel="noopener noreferrer"><img height="36" style="border:0;height:36px" src="https://storage.ko-fi.com/cdn/kofi6.png?v=6" alt="Buy Me a Coffee at ko-fi.com" /></a>
</p>
