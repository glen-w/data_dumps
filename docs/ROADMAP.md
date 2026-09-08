# Roadmap

Where `data_dumps` is headed. Guidance, not a commitment calendar.

## Shipped

### Wave 1 — Spotify Extended Streaming History

- ZIP → DuckDB (`warehouse/catalog.duckdb`)
- IPs stripped at ingest; track/artist/episode names kept
- Marimo notebook: longitudinal queries (monthly volume, kind mix, platform, country, forgotten artists, skip trends)
- Docker compose for reproducible runs
- `Source` Protocol for future dumps

### Telegram Desktop export

- `result.json` → DuckDB (`telegram.account|contacts|sessions|chats|messages|reactions`)
- Media left on disk; warehouse stores relative paths
- Marimo notebook: Wrapped-style explorer (scoreboard/streaks, me vs them, calendar, bump, reply scatter, forgotten/comebacks, reactions, calls)
- Dumps live under `~/Documents/data_dumps_raw` (outside the git tree)

### Spotify Account Data

- Separate ZIP from Extended History; additive tables only (`library_items`, `playlists`, `searches`, `account_plays`)
- Never replaces `spotify.plays`
- Explorer Library & playlists section when ingested

### LinkedIn Complete GDPR

- CSV bag → `linkedin.*` (connections, messages, career, feed activity)
- IPs/emails/phones/ads/KYC dropped at ingest
- Explorer LinkedIn tab

### Twitter / X YTD archive

- Classic HTML-viewer JS (`window.YTD.*.part0`) → `twitter.*` (tweets, likes, DMs, network snapshot)
- IPs/emails/phones/ads/device tokens dropped at ingest; media on disk only
- Explorer Twitter tab (Spotify-depth Wrapped charts)
- **Note:** newer X exports may differ; v1 targets YTD assignment format

## Wave 2 — Wrapped explorer, open enrichment, local LLM

Four phases, shippable independently after A:

| Phase | What | Unlocks |
|-------|------|---------|
| **A** | Shared `FilterState` + Wrapped questions | Year range, kind/platform/country toggles, click-to-filter, scoreboard, top-N, discovery, streaks, circadian, shuffle, comebacks |
| **B** | Expanded chart encodings | Treemap, weekday×hour heatmap, calendar, bump chart, scatter, sunburst; Wave 1 charts filter-aware |
| **C** | MusicBrainz enrichment CLI | Genre treemap, decade bars (no Spotify API) |
| **D** | Ollama-first LLM narratives | "Narrate this view" on aggregates only; optional LiteLLM extra |

### Constraints (Wave 2)

- **No Spotify API** — account closing; match on dump names only
- **Privacy** — LLM prompts are pre-aggregated KPIs + top-N lists, never raw play rows
- **Local-first LLM** — Ollama default loopback; remote LiteLLM explicit opt-in
- **Dump-only charts work** without enrichment or Ollama
- Stop notebook before ingest/enrich (DuckDB single-writer)
- **MusicBrainz is uncapped by default** — `--artist-limit` / `--track-limit` are `0` (full library). The API is free with no count quota; ~1 req/s is the only limit. See [WAREHOUSE.md](WAREHOUSE.md).

### Wave 2.1 — Hardening + tests

- `pytest` suite with synthetic DuckDB fixtures (no real dump in git)
- `ruff` / `black` / `mypy` via `uv sync --extra dev` (not run on Marimo notebooks)
- `filter_from_widgets`, `has_mb_data`, compare-previous edge cases, LLM `filter_digest` cache keys
- Notebook: horizontal ranking bars, filter clear buttons, plotly click-to-filter on platform pie and scatter
- `enrich-musicbrainz --dry-run`; Gitea CI workflow runs tests + `marimo check`

## Later

- **GUI-driven operations** — eventually all warehouse actions from the Marimo dashboard: ingest, MusicBrainz enrich, re-ingest, and LLM setup — not only explore/filter/narrate. Today ingest and enrich are CLI-only because DuckDB is single-writer; a GUI path needs an orchestration layer (stop dashboard → run job → reopen, or a dedicated writer service) without asking the user to juggle terminals. See [WAREHOUSE.md](WAREHOUSE.md) for current constraints.
- Wikidata P136 genre enrichment (deferred; MusicBrainz tags only today)

- Other GDPR sources (Amazon, Reddit) when a dump is in hand
- Cover Art Archive images after MusicBrainz
- LiteLLM sidecar in compose (TranscriptX-style gateway)
- Chat-over-corpus / RAG over every play

## Non-goals

- Spotify Web API enrichment
- Cloud LLM as silent default
- Last.fm (account deleted)
- Hosted multi-user SaaS
- Plugin registry for sources (one file per platform until needed)

## Related

| Doc | Role |
|-----|------|
| [README.md](../README.md) | Setup, Docker, privacy |
| [WAREHOUSE.md](WAREHOUSE.md) | **Single-writer lock** — UI vs ingest vs enrich |
| [../notebooks/explorer.py](../notebooks/explorer.py) | Combined Marimo dashboard (Spotify / Telegram / LinkedIn tabs) |
| [../notebooks/spotify.py](../notebooks/spotify.py) | Spotify-only notebook |
| [../notebooks/telegram.py](../notebooks/telegram.py) | Telegram-only notebook |
| [../notebooks/linkedin.py](../notebooks/linkedin.py) | LinkedIn-only notebook |
| [../notebooks/twitter.py](../notebooks/twitter.py) | Twitter-only notebook |
