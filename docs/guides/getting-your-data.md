# Getting your data

Request an export from the service, put the zip or folder anywhere you like, then ingest it. The default data root is `~/Documents/data_dumps_raw` (`DATA_DUMPS_ROOT`). Nothing in that tree belongs in git.

Stop the dashboard before every ingest. `catalog.duckdb` allows one process at a time. See [WAREHOUSE.md](../WAREHOUSE.md).

```bash
# dashboard must not be running
uv run ingest /path/to/export
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

`ingest` picks a loader by file shape. If nothing matches, it exits with `no loader matched this path`.

Wall-clock columns use a hardcoded zone, not the machine timezone: `Europe/Rome` for most sources, `Europe/Paris` for Slack, Google, Airbnb, and ChatGPT, `Europe/London` for Ring.

## Spotify Extended Streaming History

**Request.** Spotify account → Privacy → Download your data. Ask for **Extended streaming history**. It is a separate request from account data and can take weeks. The zip contains a folder named `Spotify Extended Streaming History` with `Streaming_History_Audio_*.json` and optionally `Streaming_History_Video_*.json`. An already-extracted folder with those files also works.

```bash
uv run ingest /path/to/my_spotify_data.zip
```

**Kept.** Track, artist, episode, and audiobook names; play timestamps; platform; country; skip flags.

**Dropped.** IP addresses.

**Explorer.** Spotify tab (longitudinal charts, Wrapped-style scoreboard). Genre and decade charts appear after [MusicBrainz enrichment](#optional-enrichment).

## Spotify Account Data

**Request.** The ordinary “Download your data” zip, not Extended streaming history. It contains a `Spotify Account Data` folder (`YourLibrary.json`, playlist JSON, `SearchQueries.json`).

This ingest does **not** replace `spotify.plays`.

```bash
uv run ingest /path/to/my_spotify_account_data.zip
```

**Kept.** Library items, playlists and their tracks, search queries, and a roughly one-year name-only play slice (`spotify.account_plays`).

**Dropped.** Identity, addresses, payments, and ad identifiers.

**Explorer.** Library & playlists section on the Spotify tab, once those tables exist.

## Telegram Desktop

**Request.** Telegram Desktop → Settings → Advanced → Export Telegram data. You get a folder (or a zip of that folder) whose `result.json` is the export. Media files can stay beside it; they are not copied into the warehouse.

```bash
uv run ingest /path/to/Telegram_Export
```

**Kept.** Chats, message text, reactions, contact display info. Message IDs are unique per chat: grain is `(chat_id, message_id)`.

**Dropped.** Session IPs. Media bytes stay on disk; the warehouse stores relative paths only. Saved-message file contents stay on disk as files.

**Explorer.** Telegram tab (scoreboard, me vs them, calendar, reply scatter, forgotten chats).

## LinkedIn

**Request.** Settings & Privacy → Data privacy → Get a copy of your data. Choose the **Complete** archive. Basic is a subset and may lack files the loader expects. Detect requires both `Connections.csv` and `Positions.csv` (zip or extracted folder). `Connections.csv` has a notes preamble before the header; the loader skips it.

```bash
uv run ingest /path/to/Complete_LinkedInDataExport.zip
```

**Kept.** Connections (without email), messages, positions, education, reactions, shares, comments.

**Dropped.** IPs, emails, phones, ads, inferences, receipts, and identity documents. Those files are not copied into `raw/linkedin/`.

**Explorer.** LinkedIn tab (network over time, career and location map, messages, feed activity).

## Twitter / X

**Request.** Settings → Your account → Download an archive of your data. This loader targets the classic HTML-viewer layout: `data/*.js` files that assign `window.YTD.*.part0` (at least `tweets.js`). A zip or the extracted archive folder both work.

Newer X dumps can use a different layout. v1 fails clearly instead of guessing.

```bash
uv run ingest /path/to/twitter-archive
```

**Kept.** Tweets, likes, followers and following, DM text.

**Dropped.** IPs, emails, phones, ads, and device tokens. Media stays in the archive; the warehouse stores kinds and paths only.

**Explorer.** Twitter tab.

## Slack

**Request.** This is a **workspace admin** export, not something every member can download. In the workspace admin tools: Import/Export Data → Export. You get a zip (or an extracted folder) with `users.json`, `channels.json`, and one folder per channel of daily `YYYY-MM-DD.json` files. File-conversation folders named `FC:<id>:<title>` become channels of kind `file_conversation`.

```bash
uv run ingest /path/to/slack-export.zip
```

Daily files are streamed from the zip. Only `users.json` and `channels.json` are copied to `raw/slack/`. Canvases, lists, integration logs, and huddle transcripts are skipped.

**Kept.** Display names and message text. `<@U…>` mentions resolve to `@Name`.

**Dropped.** Emails, phones, Skype handles, and avatar URLs.

**Explorer.** Slack tab, including a person spotlight. Bots and system subtypes (joins, renames) are loaded and hidden by default.

## Sleep as Android

**Request.** In the app, export or back up sleep data. The canonical package is `sleep-export.zip` containing `sleep-export.csv` plus optional `prefs.xml`, `noise.json`, and `alarms.json`. A bare `sleep-export.csv` or a folder that contains it also works.

```bash
uv run ingest /path/to/sleep-export.zip
```

**Kept.** Sessions, stage events, actigraphy samples, and alarms when `alarms.json` is present.

**Explorer.** Sleep tab. Re-export into the same zip layout for later ingests.

## Mi Band heart rate

Frozen one-off. There is no multi-format wearable pipeline, and this loader should not be extended.

**Shape.** A CSV named `heart_rate.csv` (or any CSV) with columns `dateTime,rate,rateZone`.

```bash
uv run ingest /path/to/heart_rate.csv
```

**Explorer.** Mi Band tab. Useful as a heart-rate overlay for Sleep; do not add other Mi Band metrics.

## Ring

**Request.** Ring account privacy / “download my data”. The zip is typically named `All Data Categories.zip` and must contain `DeviceEvents.csv` and `RingDeviceRegistry/Device.csv`. An extracted folder with those files also works.

```bash
uv run ingest "/path/to/All Data Categories.zip"
```

**Kept.** Device names, city and country, online/offline events, sparse motion, app events, subscriptions, accounting totals.

**Dropped.** Address, coordinates, SSID, IPs, hardware ids, and email bodies.

**Explorer.** Ring tab.

## Thunderbird

This is not a download. Point ingest at a Thunderbird profile folder that contains `global-messages-db.sqlite` (on macOS, often `~/Library/Thunderbird/Profiles/<id>.default-release`). The loader snapshots that index read-only. It does not copy or move mail directories.

Own addresses mark sent versus received. They are read from `prefs.js`, from repeatable `--identity`, or from `DATA_DUMPS_TB_IDENTITIES` (comma-separated).

```bash
uv run ingest /path/to/Thunderbird/Profiles/<id>.default-release \
  --identity you@example.com
```

**Kept.** Message metadata: subjects, addresses and domains, folders, flags, attachment names. Heuristic signals: newsletter, receipt, subscription, signup.

**Dropped.** Message bodies. Mail files stay where Thunderbird put them.

**Explorer.** Thunderbird tab.

## Browser history

**Request.** Export history as JSON with the Firefox **Sky History Export** extension (objects with `url`, `title`, `lastVisitTime`, `visitCount`). A one-time Chrome-style `history.json` in the same folder is merged. Grain is one row per URL (last visit and visit count), not individual visits.

```bash
uv run ingest /path/to/firefox/
```

**Dropped.** Sensitive query parameters (`secret`, `token`, and similar). LAN and localhost URLs are flagged private.

**Not yet.** Visit-level Firefox `places.sqlite` (needed for circadian and session charts).

**Explorer.** Browser tab.

## Amazon

**Request.** Amazon account → Request Your Data. The bundle is usually several `All Data Categories*.zip` files plus `FileDescriptions.csv`. Point ingest at the **folder**. A single curated zip, or an extracted `Your Amazon Orders/` tree, also works.

```bash
uv run ingest /path/to/amazon
```

**Kept.** Order items, orders, searches, returns, Audible / Video / Music / Kindle metadata, Rufus, and structured Alexa use. `amazon.dump_inventory` records the on-disk footprint.

**Dropped.** Voice `.wav` files (inventory only), invoice PDFs, cards, addresses, IPs, and geolocation. Spend stays multi-currency; amounts are not converted.

**Explorer.** Amazon tab. A thinner standalone notebook is `notebooks/amazon.py`.

## Duolingo

**Request.** Duolingo privacy / download-your-data export. The zip (or an extracted folder) must include `languages.csv`, `leaderboards.csv`, and `profile.csv`.

```bash
uv run ingest /path/to/duolingo.zip
```

**Kept.** Username and join time, languages, leaderboards, inventory without payment fields, friend counts, and progress events. The skill-tree blob is stored as a byte length only. Grain for progress is one row per `event_timestamp` and language pair.

**Dropped.** Auth, IPs, email and full name, blast/notify, avatars, experiments, tutor and video, DET profile, `payment_processor`, and `code_id`. Those fields are scrubbed in `raw/duolingo/` as well.

**Explorer.** Duolingo tab.

## Uber

**Request.** Uber account → Privacy → Request your data (or privacy.uber.com). The zip contains `Rider/rider_lifetime_trips-0.csv`. An extracted `Uber Data/` folder works too.

```bash
uv run ingest "/path/to/Uber Data Request.zip"
```

**Kept.** Rider trips (synthetic `trip_id`), Eats line items (`order_key` groups an order), ratings received, support ticket messages.

**Dropped.** Profile (name, email, phone, signup coordinates), payment methods, saved locations, rider and Eats app analytics (IPs, device ids, GPS), trip lat/lng, address strings, card numbers, and Eats special instructions. The same fields are scrubbed in `raw/uber/`.

**Explorer.** Uber tab. City maps use a static gazetteer because trip GPS is not stored.

## Google Takeout

**Request.** [Google Takeout](https://takeout.google.com). Download as multiple archives. Point ingest at the folder of `takeout-*.zip` files, or at an extracted `Takeout/` tree (`Takeout/Calendar` or `Takeout/My Activity` is enough to detect).

```bash
uv run ingest /path/to/google
```

**Kept.** Calendar events (grain `(calendar_name, uid)`; habit placeholders dated 1970 are skipped), Play Store library and purchases, Maps saved places (name and country only), saved lists without street addresses, photo sidecar metadata, My Activity HTML, tasks. Photos and Drive bytes stay in the zips and are inventoried only.

**Dropped.** Access logs (IPs and Gaia ids), mail mbox bodies, contacts, profile and account HTML, Pay and Wallet, street addresses, photo and Maps GPS, payment emails on Play purchases.

**Explorer.** Google tab. Local timestamps use `Europe/Paris`.

## Airbnb

**Request.** Airbnb account → Privacy → Request your personal data. The HTML export zip is usually named like `Airbnb_data_request_*.zip`.

```bash
uv run ingest /path/to/airbnb.zip
```

**Kept.** Account id (guest versus host is derived from it), reservations (grain: confirmation code), searches (city, country, and search-pin lat/lon), reviews, wishlists.

**Dropped.** Profile email, name, phone, IPs, birth date, street addresses, activity log, payments and KYC, messages, search telemetry, reservation `Message`, and search `Raw Location`. Profile HTML is not copied into `raw/airbnb/`.

**Explorer.** Airbnb tab. Local timestamps use `Europe/Paris`.

## ChatGPT

**Request.** ChatGPT → Settings → Data controls → Export data. The zip contains `conversations-NNN.json` shards, plus shared-link and library metadata.

```bash
uv run ingest /path/to/chatgpt.zip
```

**Kept.** Conversation titles, message text, model slugs, thinking and multimodal content types, shared links, library file metadata. Message grain is `(conversation_id, message_id)`.

**Dropped.** Email and phone from `user.json`, `ads.json`. `.dat` media and `chat.html` are not copied into `raw/chatgpt/`.

**Explorer.** ChatGPT tab. Local timestamps use `Europe/Paris`.

## Optional enrichment

Stop the dashboard first ([WAREHOUSE.md](../WAREHOUSE.md)).

MusicBrainz genre and decade tags for the Spotify library. Limits default to `0` (no cap): every artist and track above the minimum hours, about one request per second.

```bash
uv run enrich-musicbrainz --dry-run
uv run enrich-musicbrainz
```

Optional local narratives. The prompt is aggregates only, never raw rows. Default endpoint is loopback Ollama.

```bash
export DATA_DUMPS_LLM_ENABLED=1
export DATA_DUMPS_LLM_MODEL=qwen2.5:7b
```

Remote LiteLLM is opt-in: `uv sync --extra llm`, then `DATA_DUMPS_LLM_PROVIDER=litellm`.
