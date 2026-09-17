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
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
# Charts-only app view (Correlations + Compare + per-source tabs). Use `marimo edit` only when editing cells.
```

### Docker (reproducible run)

```bash
docker compose build
docker compose run --rm --entrypoint ingest app /data/spotify/my_spotify_data.zip
docker compose up app
# → http://127.0.0.1:2718 (no access_token)
```

**Tailscale (phone / other devices):** `https://laptop.tail1ff5ae.ts.net:2718/` via `~/Documents/server/compose/laptop/data-dumps` (Homer **data_dumps**). No Marimo password — Tailnet only. Mac + Docker Desktop must be awake.

Stop `app` before re-ingesting or enriching — see [Warehouse lock](#warehouse-lock-read-this) and [docs/WAREHOUSE.md](docs/WAREHOUSE.md). Data lives on `~/Documents/data_dumps_raw` (mounted at `/data`) — never in the image.

- ZIP → DuckDB (`warehouse/catalog.duckdb`)
- IPs stripped at ingest; track/artist/episode names kept
- Marimo notebook: longitudinal + Wrapped-style explorer

## Telegram Desktop export

```bash
uv run ingest ~/Documents/data_dumps_raw/telegram/Telegram_Export_2026-09-03
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

Docker (stop `app` first):

```bash
docker compose run --rm --entrypoint ingest app /data/telegram/Telegram_Export_2026-09-03
docker compose up app
```

- `result.json` → DuckDB (`telegram.chats`, `telegram.messages`, …)
- Media stays on disk; the warehouse stores relative paths only
- Message IDs are unique per chat: grain is `(chat_id, message_id)`
- Explorer: Wrapped-style scoreboard, me vs them, calendar/bump, reply scatter, forgotten chats

## Spotify Account Data (library / playlists / searches)

A different ZIP from Extended Streaming History. Ingest **does not replace** `spotify.plays`.

```bash
uv run ingest ~/Documents/data_dumps_raw/spotify/my_spotify_account_data_2026-09-06.zip
```

- Tables: `spotify.library_items`, `spotify.playlists`, `spotify.playlist_items`, `spotify.searches`, `spotify.account_plays` (1-year name-only slice)
- Identity, addresses, payments, and ad identifiers are not loaded
- Explorer Spotify tab grows a Library & playlists section when those tables exist

## LinkedIn GDPR export

Use the **Complete** archive (Basic is a subset). Stop the dashboard first.

```bash
uv run ingest ~/Documents/data_dumps_raw/linkedin/Complete_LinkedInDataExport_09-06-2026.zip.zip
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

Docker:

```bash
docker compose run --rm --entrypoint ingest app /data/linkedin/Complete_LinkedInDataExport_09-06-2026.zip.zip
docker compose up app
```

- CSVs → `linkedin.connections`, `linkedin.messages`, positions/education, reactions/shares/comments, …
- IPs, emails, phones, ads, inferences, receipts, and identity documents are dropped at ingest
- Explorer: LinkedIn tab (network over time, career, messages, feed activity)

## Twitter / X YTD archive

Classic HTML-viewer exports (`data/*.js` with `window.YTD.*.part0`). **Newer X dumps may use a different layout** — v1 targets this YTD format and fails clearly otherwise. Stop the dashboard first.

```bash
uv run ingest ~/Documents/data_dumps_raw/twitter/twitter-archive-2023-07-20
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

Docker:

```bash
docker compose run --rm --entrypoint ingest app /data/twitter/twitter-archive-2023-07-20
docker compose up app
```

- YTD JS → DuckDB (`twitter.tweets`, likes, followers/following, DMs, …)
- IPs, emails, phones, ads, and device tokens are dropped at ingest
- Media stays in the inbox archive; warehouse stores kinds/paths only
- Explorer: Twitter tab (Wrapped-depth scoreboard, streaks, rankings, behavior, forgotten/comebacks, longitudinal + expanded charts)

## Slack workspace

Standard workspace export zip (`users.json` + `channels.json` + one folder per channel with daily JSON). An already-extracted folder works too. Stop the dashboard first.

```bash
uv run ingest "~/Documents/data_dumps_raw/slack/REN21 Slack export May 13 2018 - Sep 26 2025.zip"
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

- Tables: `slack.users`, `slack.channels`, `slack.channel_members`, `slack.messages`, `slack.reactions`, `slack.mentions`, `slack.files`
- Daily files are streamed straight from the zip; only `users.json` / `channels.json` are copied to `raw/slack/`
- Names and message text are kept; emails, phones, Skype handles and avatars are dropped at ingest
- `<@U…>` mentions resolve to `@Name`, links to their label; `FC:<id>:<title>` file-conversation folders become channels of kind `file_conversation`
- Bots and system subtypes (joins, renames, …) are landed but hidden by default in the explorer
- Explorer: Slack tab (scoreboard, monthly human/bot/system volume, active people, channel rankings/lifecycle/forgotten/comebacks, people rankings, thread depth and time-to-first-reply, reactions, mention pairs, weekday×hour heatmap, calendar, bots) plus a **Person spotlight**: pick one person (dropdown or click a bar) to see their monthly activity, share of team, channel mix, rhythm vs team, collaborators, emoji given/received, text profile and most engaged-with messages

## Sleep as Android

Merged session export (canonical `sleep-export.zip`). Stop the dashboard first.

```bash
uv run ingest ~/Documents/data_dumps_raw/sleep_as_android/sleep-export.zip
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

- Tables: `sleep.sessions`, `sleep.events`, `sleep.actigraphy`, `sleep.alarms` (optional `alarms.json` sidecar)
- Explorer: Sleep tab (scoreboard, streaks, hours over time, bedtime/wake, weekday, calendar, stage events, tags, actigraphy sample)
- Re-export from the app into the same zip layout for future ingests
- Originals archived at `sleep_as_android/originals.zip`

## Mi Band heart rate

One-off Mi Fit CSV (`dateTime,rate,rateZone`). No multi-format pipeline.

```bash
uv run ingest ~/Documents/data_dumps_raw/miband_hr/heart_rate.csv
```

- Table: `miband.heart_rate`
- Explorer: Mi Band tab (scoreboard, daily avg, hour-of-day, weekday×hour heatmap, zones)
- Originals archived at `miband_hr/originals.zip`

## Ring

```bash
uv run ingest ~/Documents/data_dumps_raw/ring/All\ Data\ Categories.zip
```

- Tables: `ring.devices`, `ring.device_events`, `ring.events`, `ring.app_events`, `ring.subscriptions`, `ring.accounting`, `ring.dump_inventory`, …
- Explorer: Ring tab (footprint, online/offline spikes, sparse motion, app volume, billing)
- Address, coords, SSID, IPs, and hardware ids dropped at ingest

## Thunderbird mail (Gloda)

Read-only aggregation from Thunderbird’s search index — does **not** copy or move mail directories.

```bash
# Profile folder (contains global-messages-db.sqlite)
uv run ingest ~/Library/Thunderbird/Profiles/<id>.default-release

# Optional: own addresses for sent vs received (also prefs.js identities)
uv run ingest ~/Library/Thunderbird/Profiles/<id>.default-release \
  --identity you@example.com
# or: DATA_DUMPS_TB_IDENTITIES=you@example.com,you@work.com
```

- Tables: `thunderbird.accounts|folders|messages|participants|signals`
- Grain is message metadata (subjects, addresses/domains, folders, flags, attachment names) — **no bodies**
- Heuristic signals: newsletter / receipt / subscription / signup
- Explorer: Thunderbird tab (scoreboard, volume, circadian, people, domain sunburst, folders, threads, attachments, signals)

## Browser history (Firefox + legacy merge)

Sky History Export JSON (canonical) plus a one-time Chrome-style `history.json` merge. Stop the dashboard first.

```bash
# Both files under firefox/ (dated Sky export is canonical; history.json is merged)
uv run ingest ~/Documents/data_dumps_raw/firefox/
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

- Tables: `browser.pages`, `browser.ingest_meta`
- Grain is **URL-level** (last visit + visit count), not individual visits
- Sensitive query params (`secret`, `token`, …) stripped at ingest; LAN/localhost flagged private
- Explorer: Browser tab (scoreboard, domains/hosts/pages, categories, last-seen calendar, search queries, forgotten gems, routines, comebacks, local hosts, path tree)
- Future: visit-level `places.sqlite` for circadian / rabbit-hole sessions

## Amazon GDPR (multipart)

Amazon’s “Request your data” bundle is usually several `All Data Categories*.zip` files plus `FileDescriptions.csv`. Stop the dashboard first.

```bash
uv run ingest ~/Documents/data_dumps_raw/amazon
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
# or: uv run marimo run notebooks/amazon.py --host 127.0.0.1 --port 2718
```

- Prefer pointing at the **folder** (all parts); a single curated zip also works
- Tables: `amazon.order_items|orders|searches|…` plus Alexa structured use and `dump_inventory`
- Voice `.wav` / invoice PDFs / cards / addresses / IPs / geolocation are **not** loaded (voice appears only as footprint inventory)
- Explorer: Amazon tab — spend (multi-currency), product types, search funnel, Alexa utterances, dump footprint

## Duolingo GDPR export

Stop the dashboard first ([WAREHOUSE.md](docs/WAREHOUSE.md)).

```bash
uv run ingest ~/Documents/data_dumps_raw/duolingo   # keep-list CSVs already on disk
# or: uv run ingest /path/to/duolingo.zip
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

- Tables: `duolingo.account|languages|leaderboards|inventory|friends|progress_events`
- Grain: progress events = one row per `event_timestamp` + language pair (tree blob stored as byte length only)
- Dropped at ingest: auth, IPs, emails/fullname, blast/notify, avatars, experiments, tutor/video, DET profile, `payment_processor` / `code_id` (profile/inventory scrubbed in `raw/duolingo/` too)
- Explorer: Duolingo tab (light — scoreboard, XP languages, league tiers, progress rhythm, inventory)

## Uber GDPR export

Stop the dashboard first ([WAREHOUSE.md](docs/WAREHOUSE.md)).

```bash
uv run ingest ~/Documents/data_dumps_raw/uber/"Uber Data Request 820F71B0.zip"
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

- Tables: `uber.trips|order_items|ratings|support_messages`
- Grain: `trips` = one rider trip (synthetic `trip_id`); `order_items` = one Eats line item (`order_key` groups an order)
- Dropped at ingest: profile (name/email/phone/signup coords), payment methods, saved locations, rider/eats app analytics (IPs, device ids, GPS), trip lat/lng + address strings + card numbers, Eats special instructions (scrubbed in `raw/uber/` too)
- Explorer: Uber tab (scoreboard, streaks, cities/products, circadian + calendar, forgotten/comeback cities, city-rank bump, fare×distance scatter, Eats)

### Compare (cross-source)

Explorer **Compare** tab: overlay monthly source totals and entity/thread series as % of each series’ max, with a Pearson correlation heatmap of those shapes. Series merge from `contributions.CONTRIBUTIONS` (descriptors in `contribution_series.py` via `series_catalog.make_*` factories). Catalog includes secondary totals (Sleep snore/noise, Amazon Alexa/Kindle/searches/Audible/Video/Music, Browser search URLs, Ring flips/motion/app, Slack active people, Telegram reactions, LinkedIn connections/reactions/shares, Twitter DMs, Thunderbird signals, Spotify Account searches, Duolingo inventory/league tier + language entity, Uber trips/Eats + city entity) when those tables are ingested — still explicit registration, not warehouse column discovery.

### Correlations (cross-source)

Explorer **Correlations** tab: daily-first Pearson matrix across source totals, ranked pairs (Spearman too), focus scatter + z-score overlay, and ±7 day lag scan. Presets: Life rhythm / Comms / Sleep & body. Metrics merge from the same `CONTRIBUTIONS` registry (same expanded totals as Compare when grain allows; monthly-only metrics drop out on daily grain).

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
spotify/              # Extended History ZIP + Account Data ZIP
telegram/             # Desktop export folder (result.json + media)
linkedin/             # Complete (and optional Basic) GDPR ZIP
twitter/              # YTD HTML-viewer archive folder (data/*.js + media)
slack/                # workspace export zip
sleep_as_android/     # sleep-export.zip + originals.zip
miband_hr/            # heart_rate.csv + originals.zip
ring/                 # All Data Categories.zip (Ring GDPR)
uber/                 # Uber Data Request ….zip
raw/spotify/          # extracted Streaming_History JSON
raw/spotify_account/  # Account Data JSON (library/playlists/searches only)
raw/telegram/         # result.json copy only (not media)
raw/linkedin/         # ingested CSVs (PII files never copied)
raw/twitter/          # ingested YTD JS keep-list (PII/ad files never copied)
raw/slack/            # users.json + channels.json copies (daily files read from zip)
raw/sleep/            # extracted sleep-export.csv (+ sidecars)
raw/miband/           # heart_rate.csv copy
raw/ring/             # keep-list CSVs + flattened app_events.csv
raw/duolingo/         # keep-list CSVs only (PII/avatar files never copied)
raw/uber/             # scrubbed trips/orders/ratings/support (no profile/payments/GPS)
warehouse/            # DuckDB catalog + llm_cache
```

Docker mounts that folder at `/data` and sets `DATA_DUMPS_ROOT=/data`. `DATA_DUMPS_WAREHOUSE` overrides the DuckDB file path.

## Adding a source later

Follow **[docs/guides/add-a-dump.md](docs/guides/add-a-dump.md)** (agents: [AGENTS.md](AGENTS.md), rule `.cursor/rules/add-dump.mdc`).

Short version: implement `Source` in `src/data_dumps/sources/<slug>.py` (`detect` / `load` / `tables` / `inventory`), append one `Contribution` in `contributions.py`, add synthetic tests with PII drop assertions, then queries + explorer tab when that is the lane. Thin explicit registry — no dynamic discovery.

## Privacy

Do not commit dumps, raw JSON, DuckDB files, or `.env`. LLM prompts contain pre-aggregated stats only. Default LLM endpoint is loopback Ollama; remote LiteLLM is explicit opt-in. Telegram ingest keeps message text and contact phones in the personal warehouse; session IPs and media bytes are not loaded. Saved-message file contents stay on disk as files. LinkedIn ingest keeps message text; connection emails, logins/IPs, phones, ads, and KYC files are not loaded. Twitter ingest keeps tweet/DM text; emails, IPs, phones, ads, and device tokens are not loaded.

## Tests

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run black --check src tests
uv run mypy src
uv run python -m marimo check notebooks/explorer.py notebooks/spotify.py notebooks/telegram.py notebooks/linkedin.py notebooks/twitter.py notebooks/sleep.py
```

Do not run Black or Ruff on `notebooks/` — Marimo cell structure is not a formatter target.

Stop the Marimo notebook or `docker compose stop app` before `ingest` or `enrich-musicbrainz`. Details: [docs/WAREHOUSE.md](docs/WAREHOUSE.md).
