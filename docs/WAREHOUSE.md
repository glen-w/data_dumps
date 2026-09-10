# Warehouse operations

`~/Documents/data_dumps_raw/warehouse/catalog.duckdb` is the single DuckDB catalog. **Only one process may use it at a time** for ingest, enrichment, or the Marimo dashboard.

DuckDB does not allow a second connection while another holds the file lock — even when the notebook opens the DB **read-only**. If you see `Conflicting lock` or `Cannot execute statement … read-only mode`, something else still has the warehouse open.

## What conflicts with what

| You are running | Safe to run in parallel |
|-----------------|-------------------------|
| Marimo (`marimo run` / `edit` or `docker compose up app`) | Nothing that touches `catalog.duckdb` |
| `uv run ingest …` | Nothing else on the warehouse |
| `uv run enrich-musicbrainz` | Nothing else on the warehouse |

**Do not** run the Spotify UI and MusicBrainz enrichment at the same time.

## Typical workflows

### Explore listening (dashboard)

```bash
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
# or: docker compose up app
# Use `marimo edit` only when changing notebook cells (shows code).
```

### Ingest a new dump

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest ~/Documents/data_dumps_raw/spotify/my_spotify_data.zip`
3. Start the dashboard again

### Ingest Spotify Account Data (library / playlists)

Does **not** replace Extended History `spotify.plays`.

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest ~/Documents/data_dumps_raw/spotify/my_spotify_account_data_2026-09-06.zip`
3. Start the dashboard again — Library & playlists appears on the Spotify tab

### Ingest a Telegram Desktop export

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest ~/Documents/data_dumps_raw/telegram/Telegram_Export_2026-09-03`
3. `uv run marimo run notebooks/explorer.py` (Telegram tab)

### Ingest a LinkedIn Complete export

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest ~/Documents/data_dumps_raw/linkedin/Complete_LinkedInDataExport_09-06-2026.zip.zip`
3. Start the dashboard again (LinkedIn tab)

### Ingest a Twitter / X YTD archive

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest ~/Documents/data_dumps_raw/twitter/twitter-archive-2023-07-20`
3. Start the dashboard again (Twitter tab)

Classic `window.YTD.*.part0` JS exports are supported; newer X dumps may need schema updates.

### Ingest Slack

Workspace export zip (or extracted folder) with `users.json`, `channels.json` and `<channel>/<YYYY-MM-DD>.json`.

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest "~/Documents/data_dumps_raw/slack/REN21 Slack export May 13 2018 - Sep 26 2025.zip"`
3. Start the dashboard again (Slack tab)

Tables and grains:

| Table | Grain | Notes |
|-------|-------|-------|
| `slack.users` | user_id | no email / phone / avatar |
| `slack.channels` | channel_id | `kind` = `channel` or `file_conversation`; first/last ts and n_messages filled after load |
| `slack.channel_members` | (channel_id, user_id) | from `channels[].members` |
| `slack.messages` | (channel_id, ts) | all subtypes; `is_bot`, `is_reply`, `is_thread_root`, `parent_user_id`, resolved `text`, Paris local time |
| `slack.reactions` | (channel_id, ts, emoji, user_id) | one row per reacting user |
| `slack.mentions` | (channel_id, ts, mentioned_user_id) | from `<@U…>` in text |
| `slack.files` | (channel_id, ts, file_id) | metadata only |

Full REN21 export (~34k daily files, 1 GB uncompressed) loads in under 10 s; nothing is extracted to disk except the two root JSONs.

### Ingest Sleep as Android

Canonical package: `sleep-export.zip` (`sleep-export.csv` + optional `prefs.xml` / `noise.json` / `alarms.json`).

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest ~/Documents/data_dumps_raw/sleep_as_android/sleep-export.zip`
3. Start the dashboard again (Sleep tab)

Tables: `sleep.sessions`, `sleep.events`, `sleep.actigraphy`, `sleep.alarms` (from the `alarms.json` sidecar; empty when absent). Future app re-exports use the same zip layout.

### Ingest Mi Band heart rate (one-off)

Merged CSV with `dateTime,rate,rateZone`.

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest ~/Documents/data_dumps_raw/miband_hr/heart_rate.csv`
3. Start the dashboard again (Mi Band tab)

### Ingest browser history (Firefox Sky + legacy)

Sky History Export JSON (canonical dated file) plus optional Chrome-style `history.json` (may be two concatenated arrays).

1. **Stop** Marimo or `docker compose stop app`
2. Put files under `~/Documents/data_dumps_raw/firefox/` then:
   `uv run ingest ~/Documents/data_dumps_raw/firefox/`
3. Start the dashboard again (Browser tab)

| Table | Grain | Notes |
|-------|-------|-------|
| `browser.pages` | url | last visit + visit count; secrets stripped from query string; private/LAN flagged |
| `browser.ingest_meta` | file | per-file raw/kept counts and source label |

Visit-level Firefox `places.sqlite` → `browser.visits` is deferred (needed for circadian / rabbit-hole sessions).

### MusicBrainz enrichment (genres / decades)

`--artist-limit` and `--track-limit` default to **`0` (no cap)**. The CLI assumes you want the **full dataset** — every artist/track above the min lifetime hours — not a sample. MusicBrainz has no free-tier count quota; the only API constraint is **~1 request/second** per IP.

1. **Stop** Marimo or `docker compose stop app`
2. Preview scope (optional; also uncapped unless you pass limits):

   ```bash
   uv run enrich-musicbrainz --dry-run
   # optional smaller preview:
   uv run enrich-musicbrainz --dry-run --artist-limit 200 --track-limit 500
   ```

3. Run enrichment (default = full library):

   ```bash
   uv run enrich-musicbrainz
   # optional smaller batch:
   uv run enrich-musicbrainz --artist-limit 200 --track-limit 500
   ```

4. Start the dashboard again — genre/decade charts appear when `mb_match` has data

Each artist/track takes two calls (search + lookup), so a full crawl of thousands of names takes hours. Pass `--artist-limit N` / `--track-limit N` only if you want a shorter batch.

### Docker

```bash
docker compose stop app          # release warehouse lock
docker compose run --rm --entrypoint ingest app /data/spotify/my_spotify_data.zip
docker compose run --rm --entrypoint ingest app /data/spotify/my_spotify_account_data_2026-09-06.zip
docker compose run --rm --entrypoint ingest app /data/telegram/Telegram_Export_2026-09-03
docker compose run --rm --entrypoint ingest app /data/linkedin/Complete_LinkedInDataExport_09-06-2026.zip.zip
docker compose run --rm --entrypoint ingest app /data/twitter/twitter-archive-2023-07-20
docker compose run --rm --entrypoint ingest app "/data/slack/REN21 Slack export May 13 2018 - Sep 26 2025.zip"
docker compose run --rm --entrypoint ingest app /data/sleep_as_android/sleep-export.zip
docker compose run --rm --entrypoint ingest app /data/miband_hr/heart_rate.csv
docker compose run --rm --entrypoint ingest app /data/firefox/
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
