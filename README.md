# data_dumps

Local tools to ingest and explore personal GDPR data exports. Private Gitea repo; dumps and warehouses stay off git.

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

Stop `app` before re-ingesting (DuckDB is single-writer). Data (`raw/`, `warehouse/`, `*.zip`) lives on the repo bind mount — never in the image.

- ZIP → DuckDB (`warehouse/catalog.duckdb`, gitignored)
- IPs stripped at ingest; track/artist/episode names kept
- Marimo notebook: longitudinal queries, not Wrapped

## Layout

```
raw/                  # extracted JSON (gitignored)
warehouse/            # DuckDB catalog (gitignored)
*.zip                 # source dumps (gitignored)
src/sources/          # per-platform loaders (Protocol: detect / load / tables)
notebooks/            # Marimo exploration
```

## Adding a source later

Implement `Source` in `src/sources/base.py`: `detect(path) -> bool`, `load(path, conn)`, `tables() -> list[str]`. One file per platform when a dump is in hand — no plugin registry yet.

## Privacy

Do not commit dumps, raw JSON, DuckDB files, or `.env`. Do not send rows to cloud LLMs.
