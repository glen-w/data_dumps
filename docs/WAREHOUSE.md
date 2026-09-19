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
2. `uv run ingest /path/to/my_spotify_data.zip`
3. Start the dashboard again

### Ingest Spotify Account Data (library / playlists)

Does **not** replace Extended History `spotify.plays`.

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest /path/to/my_spotify_account_data.zip`
3. Start the dashboard again — Library & playlists appears on the Spotify tab

### Ingest a Telegram Desktop export

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest /path/to/Telegram_Export`
3. `uv run marimo run notebooks/explorer.py` (Telegram tab)

### Ingest a LinkedIn Complete export

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest /path/to/Complete_LinkedInDataExport.zip`
3. Start the dashboard again (LinkedIn tab)

### Ingest a Twitter / X YTD archive

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest /path/to/twitter-archive`
3. Start the dashboard again (Twitter tab)

Classic `window.YTD.*.part0` JS exports are supported; newer X dumps may need schema updates.

### Ingest Slack

Workspace export zip (or extracted folder) with `users.json`, `channels.json` and `<channel>/<YYYY-MM-DD>.json`.

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest /path/to/slack-export.zip`
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

A large export (tens of thousands of daily files) loads in seconds; nothing is extracted to disk except the two root JSONs.

### Ingest Sleep as Android

Canonical package: `sleep-export.zip` (`sleep-export.csv` + optional `prefs.xml` / `noise.json` / `alarms.json`).

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest /path/to/sleep-export.zip`
3. Start the dashboard again (Sleep tab)

Tables: `sleep.sessions`, `sleep.events`, `sleep.actigraphy`, `sleep.alarms` (from the `alarms.json` sidecar; empty when absent). Future app re-exports use the same zip layout.

### Ingest Mi Band heart rate (one-off)

Merged CSV with `dateTime,rate,rateZone`.

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest /path/to/heart_rate.csv`
3. Start the dashboard again (Mi Band tab)

### Ingest Ring GDPR

`All Data Categories.zip` from a Ring data request (devices, online/offline, sparse motion retention, app telemetry, subscriptions).

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest "/path/to/All Data Categories.zip"`
3. Start the dashboard again (Ring tab)

Tables: `ring.devices`, `ring.setups`, `ring.locations`, `ring.device_events`, `ring.events`, `ring.app_events`, `ring.subscriptions`, `ring.accounting`, `ring.dump_inventory`. Address, coords, SSID, IPs, and hardware ids are dropped; city/country and device names are kept.

### Ingest browser history (Firefox Sky + legacy)

Sky History Export JSON (canonical dated file) plus optional Chrome-style `history.json` (may be two concatenated arrays).

1. **Stop** Marimo or `docker compose stop app`
2. Put the JSON files in one folder, then:
   `uv run ingest /path/to/firefox/`
3. Start the dashboard again (Browser tab)

| Table | Grain | Notes |
|-------|-------|-------|
| `browser.pages` | url | last visit + visit count; secrets stripped from query string; private/LAN flagged |
| `browser.ingest_meta` | file | per-file raw/kept counts and source label |

Visit-level Firefox `places.sqlite` → `browser.visits` is deferred (needed for circadian / rabbit-hole sessions).

### Ingest Amazon GDPR (multipart)

Folder of `All Data Categories*.zip` (+ `FileDescriptions.csv`), or a single curated zip / extracted `Your Amazon Orders/` tree.

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest /path/to/amazon`
3. Start the dashboard again (Amazon tab)

Commerce, search, returns, Audible/Video/Music, Kindle, Rufus, and Alexa **structured** tables land in `amazon.*`. Voice WAVs and payment/address PII are skipped; `amazon.dump_inventory` records the full on-disk footprint.

### Ingest Uber GDPR

Zip named like `Uber Data Request ….zip` (or extracted `Uber Data/` folder) with `Rider/rider_lifetime_trips-0.csv`.

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest "/path/to/Uber Data Request.zip"`
3. Start the dashboard again (Uber tab)

Tables: `uber.trips`, `uber.order_items`, `uber.ratings`, `uber.support_messages`. Profile, payment methods, saved locations, and app GPS analytics are not loaded; trip coords/address strings/card numbers and Eats special instructions are scrubbed.

### Ingest Google Takeout (multipart)

Folder of `takeout-*.zip` parts (or an extracted `Takeout/` tree). Large Photos/Drive/Mail members are inventoried but not copied into the warehouse.

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest /path/to/google`
3. Start the dashboard again (Google tab)

Keep-list: Calendar ICS, Play Store (purchases scrub payment emails), Maps your-places (name + country only), Saved lists (no Addresses), photo supplemental metadata (no GPS), My Activity HTML, Tasks. Access logs, mail mbox, contacts, Pay/Wallet, and street/GPS fields are dropped. `google.dump_inventory` records the full on-disk footprint.

### Ingest Airbnb personal data

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest /path/to/airbnb.zip`
3. Start the dashboard again — Airbnb tab (search map + reservations)

Keep-list HTML: reservations, search_history, reviews, wishlists. Profile is read only for account id (not copied to `raw/airbnb/`). Activity log, payments, KYC, messages, and search telemetry are skipped.

### Ingest ChatGPT export

1. **Stop** Marimo or `docker compose stop app`
2. `uv run ingest /path/to/chatgpt.zip`
3. Start the dashboard again — ChatGPT tab

Keep-list: `conversations-*.json`, `shared_conversations.json`, `conversation_asset_file_names.json`, `library_files.json`, stripped `account.json`. Not copied: `.dat` media, `chat.html`, email/phone from `user.json`, `ads.json`.

### Tools email index

The Tools tab does not ingest a new dump. It reads the open warehouse (message text, Thunderbird from/to) plus original export files the loaders skip (account emails, Slack profiles, Google contacts, Amazon mail files) and, when it can see the profile, Thunderbird message bodies. Addresses are not written back into source tables. Docker needs the profile mounted read-only (`DATA_DUMPS_TB_PROFILE`); the repo compose and the laptop compose both do that. A cache file `warehouse/email_inventory.json` sits next to `catalog.duckdb` (outside git). Opening Tools rebuilds it when inputs change; that does not need the warehouse write lock. `uv run email-inventory` prints counts and does need a free warehouse, because it opens `catalog.duckdb`.

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

Paths below are inside the container (`/data` is the bind-mounted data root).

```bash
docker compose stop app          # release warehouse lock
docker compose run --rm --entrypoint ingest app /data/spotify/my_spotify_data.zip
docker compose run --rm --entrypoint ingest app /data/spotify/my_spotify_account_data.zip
docker compose run --rm --entrypoint ingest app /data/telegram/Telegram_Export
docker compose run --rm --entrypoint ingest app /data/linkedin/Complete_LinkedInDataExport.zip
docker compose run --rm --entrypoint ingest app /data/twitter/twitter-archive
docker compose run --rm --entrypoint ingest app /data/slack/slack-export.zip
docker compose run --rm --entrypoint ingest app /data/sleep_as_android/sleep-export.zip
docker compose run --rm --entrypoint ingest app /data/miband_hr/heart_rate.csv
docker compose run --rm --entrypoint ingest app "/data/ring/All Data Categories.zip"
docker compose run --rm --entrypoint ingest app /data/firefox/
docker compose run --rm --entrypoint ingest app /data/amazon
docker compose run --rm --entrypoint ingest app "/data/uber/Uber Data Request.zip"
docker compose run --rm --entrypoint ingest app /data/airbnb/airbnb.zip
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
- [guides/getting-your-data.md](guides/getting-your-data.md) — export index; per-service pages under [guides/services/](guides/services/)
