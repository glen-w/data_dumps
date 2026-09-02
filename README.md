# data_dumps

Local tools to ingest and explore personal GDPR data exports. Private Gitea repo; dumps and warehouses stay off git.

## Warehouse lock (read this)

`warehouse/catalog.duckdb` is **single-writer**. The Marimo dashboard and `enrich-musicbrainz` / `ingest` **cannot run at the same time** — even though the notebook uses a read-only connection, DuckDB still blocks the other process.

| Task | First step |
|------|------------|
| Ingest a zip | Stop Marimo or `docker compose stop app` |
| MusicBrainz enrich | Stop Marimo or `docker compose stop app` |
| Open dashboard | Stop any running ingest/enrich |

Full workflows, Docker, and troubleshooting: **[docs/WAREHOUSE.md](docs/WAREHOUSE.md)**

## Wave 1 — Spotify Extended Streaming History

### Local (dev)

```bash
uv sync
uv run ingest my_spotify_data.zip
uv run marimo edit notebooks/spotify.py
```

### Docker (reproducible run)

```bash
docker compose build
docker compose run --rm --entrypoint ingest app /data/my_spotify_data.zip
docker compose up app
# → http://127.0.0.1:2718 — token printed in logs (marimo ?access_token=…)
```

Stop `app` before re-ingesting or enriching — see [Warehouse lock](#warehouse-lock-read-this) and [docs/WAREHOUSE.md](docs/WAREHOUSE.md). Data (`raw/`, `warehouse/`, `*.zip`) lives on the repo bind mount — never in the image.

- ZIP → DuckDB (`warehouse/catalog.duckdb`, gitignored)
- IPs stripped at ingest; track/artist/episode names kept
- Marimo notebook: longitudinal + Wrapped-style explorer

## Wave 2 — Wrapped explorer, open enrichment, local LLM

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full plan.

```bash
# MusicBrainz genre/decade enrichment — stop dashboard first (see docs/WAREHOUSE.md)
uv run enrich-musicbrainz --dry-run              # preview (default cap: 200 artists, 500 tracks)
uv run enrich-musicbrainz --dry-run --artist-limit 0 --track-limit 0  # full counts
uv run enrich-musicbrainz
```

# Optional: local LLM narratives (Ollama on loopback)
export DATA_DUMPS_LLM_ENABLED=1
export DATA_DUMPS_LLM_MODEL=qwen2.5:7b
```

Dashboard features:

- Shared filters (year range, kind, platform, country, artist search/click)
- Wrapped scoreboard, top-N rankings, discovery vs repeats, streaks, circadian heatmap
- Treemap, calendar, bump chart, scatter; Wave 1 charts are filter-aware
- Genre/decade charts when MusicBrainz enrichment has run
- "Narrate this view" sends **aggregates only** to Ollama (never raw rows)

Optional LiteLLM: `uv sync --extra llm` then `DATA_DUMPS_LLM_PROVIDER=litellm`.

## Layout

```
raw/                  # extracted JSON (gitignored)
warehouse/            # DuckDB catalog + llm_cache (gitignored)
*.zip                 # source dumps (gitignored)
src/data_dumps/       # ingest, queries, enrich, llm
notebooks/            # Marimo exploration
docs/                 # ROADMAP, WAREHOUSE operations
```

Paths default to the repo root. Override with `DATA_DUMPS_ROOT` (dumps / `raw/` / `warehouse/`) and `DATA_DUMPS_WAREHOUSE` (DuckDB file). Docker sets `DATA_DUMPS_ROOT=/data`.

## Adding a source later

Implement `Source` in `src/data_dumps/sources/base.py`: `detect(path) -> bool`, `load(path, conn)`, `tables() -> list[str]`. One file per platform when a dump is in hand — no plugin registry yet.

## Privacy

Do not commit dumps, raw JSON, DuckDB files, or `.env`. LLM prompts contain pre-aggregated stats only. Default LLM endpoint is loopback Ollama; remote LiteLLM is explicit opt-in.

## Tests

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run black --check src tests
uv run mypy src
uv run python -m marimo check notebooks/spotify.py
```

Do not run Black or Ruff on `notebooks/` — Marimo cell structure is not a formatter target.

Stop the Marimo notebook or `docker compose stop app` before `ingest` or `enrich-musicbrainz`. Details: [docs/WAREHOUSE.md](docs/WAREHOUSE.md).
