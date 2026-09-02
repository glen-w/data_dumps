# Warehouse operations

`warehouse/catalog.duckdb` is the single DuckDB catalog for this repo. **Only one process may use it at a time** for ingest, enrichment, or the Marimo dashboard.

DuckDB does not allow a second connection while another holds the file lock — even when the notebook opens the DB **read-only**. If you see `Conflicting lock` or `Cannot execute statement … read-only mode`, something else still has the warehouse open.

## What conflicts with what

| You are running | Safe to run in parallel |
|-----------------|-------------------------|
| Marimo (`marimo edit` or `docker compose up app`) | Nothing that touches `catalog.duckdb` |
| `uv run ingest …` | Nothing else on the warehouse |
| `uv run enrich-musicbrainz` | Nothing else on the warehouse |

**Do not** run the Spotify UI and MusicBrainz enrichment at the same time.

## Typical workflows

### Explore listening (dashboard)

```bash
uv run marimo edit notebooks/spotify.py --host 127.0.0.1 --port 2718
# or: docker compose up app
```

### Ingest a new dump

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest my_spotify_data.zip`
3. Start the dashboard again

### MusicBrainz enrichment (genres / decades)

1. **Stop** Marimo or `docker compose stop app`
2. Preview scope (optional):

   ```bash
   uv run enrich-musicbrainz --dry-run
   # full catalog counts (no cap):
   uv run enrich-musicbrainz --dry-run --artist-limit 0 --track-limit 0
   ```

3. Run enrichment (defaults: top **200** artists, **500** tracks by lifetime hours — not your whole library):

   ```bash
   uv run enrich-musicbrainz
   # larger batch:
   uv run enrich-musicbrainz --artist-limit 1000 --track-limit 2000
   ```

4. Start the dashboard again — genre/decade charts appear when `mb_match` has data

MusicBrainz rate limit is ~1 request/second. A full artist crawl of thousands of names takes hours; the default limits are intentional for a first batch.

### Docker

```bash
docker compose stop app          # release warehouse lock
docker compose run --rm --entrypoint ingest app /data/my_spotify_data.zip
docker compose run --rm --entrypoint enrich-musicbrainz app --dry-run
docker compose up app
```

## Quick checks

```bash
# Who holds port 2718 (local Marimo or compose)?
lsof -i :2718

# Stop compose notebook
docker compose stop app
```

## Related

- [README.md](../README.md) — setup
- [ROADMAP.md](ROADMAP.md) — features and constraints
