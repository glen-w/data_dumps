# data_dumps

Local tools to ingest and explore personal GDPR data exports. Private Gitea repo; dumps and warehouses stay off git.

## Warehouse lock (read this)

`~/Documents/data_dumps_raw/warehouse/catalog.duckdb` is **single-writer**. The Marimo dashboard and `enrich-musicbrainz` / `ingest` **cannot run at the same time** — even though the notebook uses a read-only connection, DuckDB still blocks the other process.

| Task | First step |
|------|------------|
| Ingest a zip / Telegram export | Stop Marimo or `docker compose stop app` |
| MusicBrainz enrich | Stop Marimo or `docker compose stop app` |
| Open dashboard | Stop any running ingest/enrich |

Full workflows, Docker, and troubleshooting: **[docs/WAREHOUSE.md](docs/WAREHOUSE.md)**

## Wave 1 — Spotify Extended Streaming History

### Local (dev)

```bash
uv sync
uv run ingest ~/Documents/data_dumps_raw/spotify/my_spotify_data.zip
uv run marimo edit notebooks/spotify.py
```

### Docker (reproducible run)

```bash
docker compose build
docker compose run --rm --entrypoint ingest app /data/spotify/my_spotify_data.zip
docker compose up app
# → http://127.0.0.1:2718 — token printed in logs (marimo ?access_token=…)
```

Stop `app` before re-ingesting or enriching — see [Warehouse lock](#warehouse-lock-read-this) and [docs/WAREHOUSE.md](docs/WAREHOUSE.md). Data lives on `~/Documents/data_dumps_raw` (mounted at `/data`) — never in the image.

- ZIP → DuckDB (`warehouse/catalog.duckdb`)
- IPs stripped at ingest; track/artist/episode names kept
- Marimo notebook: longitudinal + Wrapped-style explorer

## Telegram Desktop export

```bash
uv run ingest ~/Documents/data_dumps_raw/telegram/Telegram_Export_2026-09-03
uv run marimo edit notebooks/telegram.py
```

Docker (stop `app` first):

```bash
docker compose run --rm --entrypoint ingest app /data/telegram/Telegram_Export_2026-09-03
docker compose run --rm --entrypoint marimo app edit notebooks/telegram.py --host 0.0.0.0 --port 2718 --headless --token
```

- `result.json` → DuckDB (`telegram.chats`, `telegram.messages`, …)
- Media stays on disk; the warehouse stores relative paths only
- Message IDs are unique per chat: grain is `(chat_id, message_id)`
- Explorer: Wrapped-style scoreboard, me vs them, calendar/bump, reply scatter, forgotten chats

## Wave 2 — Wrapped explorer, open enrichment, local LLM

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full plan.

```bash
# MusicBrainz genre/decade enrichment — stop dashboard first (see docs/WAREHOUSE.md)
# --artist-limit / --track-limit default to 0 (no cap): full library is the assumed run.
uv run enrich-musicbrainz --dry-run              # preview pending counts (uncapped)
uv run enrich-musicbrainz                         # enrich everything above min-hours (~1 req/s)
uv run enrich-musicbrainz --artist-limit 200 --track-limit 500  # optional smaller batch
```

```bash
# Optional: local LLM narratives (Ollama on loopback)
export DATA_DUMPS_LLM_ENABLED=1
export DATA_DUMPS_LLM_MODEL=qwen2.5:7b
```

Dashboard features (Spotify):

- Shared filters (year range, kind, platform, country, artist search/click)
- Wrapped scoreboard, top-N rankings, discovery vs repeats, streaks, circadian heatmap
- Treemap, calendar, bump chart, scatter; Wave 1 charts are filter-aware
- Genre/decade charts when MusicBrainz enrichment has run
- "Narrate this view" sends **aggregates only** to Ollama (never raw rows)

Optional LiteLLM: `uv sync --extra llm` then `DATA_DUMPS_LLM_PROVIDER=litellm`.

## Layout

Repo (code only):

```
src/data_dumps/       # ingest, queries, enrich, llm
notebooks/            # Marimo exploration
docs/                 # ROADMAP, WAREHOUSE operations
```

Data root (default `~/Documents/data_dumps_raw`, override with `DATA_DUMPS_ROOT`):

```
spotify/              # source ZIP
telegram/             # Desktop export folder (result.json + media)
raw/spotify/          # extracted Streaming_History JSON
raw/telegram/         # result.json copy only (not media)
warehouse/            # DuckDB catalog + llm_cache
```

Docker mounts that folder at `/data` and sets `DATA_DUMPS_ROOT=/data`. `DATA_DUMPS_WAREHOUSE` overrides the DuckDB file path.

## Adding a source later

Implement `Source` in `src/data_dumps/sources/base.py`: `detect(path) -> bool`, `load(path, conn)`, `tables() -> list[str]`, `inventory(conn) -> dict`. One file per platform when a dump is in hand — no plugin registry yet.

## Privacy

Do not commit dumps, raw JSON, DuckDB files, or `.env`. LLM prompts contain pre-aggregated stats only. Default LLM endpoint is loopback Ollama; remote LiteLLM is explicit opt-in. Telegram ingest keeps message text and contact phones in the personal warehouse; session IPs and media bytes are not loaded. Saved-message file contents stay on disk as files.

## Tests

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run black --check src tests
uv run mypy src
uv run python -m marimo check notebooks/spotify.py notebooks/telegram.py
```

Do not run Black or Ruff on `notebooks/` — Marimo cell structure is not a formatter target.

Stop the Marimo notebook or `docker compose stop app` before `ingest` or `enrich-musicbrainz`. Details: [docs/WAREHOUSE.md](docs/WAREHOUSE.md).
