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
- Explorer LinkedIn tab (career location map from positions)

### Twitter / X YTD archive

- Classic HTML-viewer JS (`window.YTD.*.part0`) → `twitter.*` (tweets, likes, DMs, network snapshot)
- IPs/emails/phones/ads/device tokens dropped at ingest; media on disk only
- Explorer Twitter tab (Spotify-depth Wrapped charts)
- **Note:** newer X exports may differ; v1 targets YTD assignment format

### Slack workspace

- Export zip streamed → `slack.users|channels|channel_members|messages|reactions|mentions|files`
- Emails/phones/avatars dropped; names + text kept; mentions resolved to `@Name`
- Explorer Slack tab (workspace activity, channels, people, threads/latency, reactions, mentions, rhythm, bots) + Person spotlight (one user vs team, collaborators)
- Loader/user-mapping/text-cleaning ported from the standalone `slack analysis` project; its sick-days/sentiment NLP stack was deliberately not ported
- **Later:** canvases.json, lists.json, integration_logs.json, huddle transcripts are skipped today

### Sleep as Android

- Merged `sleep-export.zip` → `sleep.sessions|events|actigraphy|alarms` (`alarms.json` sidecar parsed when present)
- Explorer Sleep tab (scoreboard, streaks, longitudinal, circadian, calendar, events/stages, actigraphy sample)
- Standalone `notebooks/sleep.py`
- Future re-exports: same zip layout as the Android app

### Mi Band heart rate (one-off, frozen)

- Merged `heart_rate.csv` → `miband.heart_rate`
- Explorer Mi Band tab (scoreboard, longitudinal, circadian/calendar, resting HR, zones, anomalies; optional Sleep overlay)
- **No further work** — one-off dump only; keep ingest + existing tab for Sleep HR joins; do not deepen, re-ingest formats, or add non-HR metrics

### Thunderbird mail (Gloda)

- Read-only snapshot of `global-messages-db.sqlite` → `thunderbird.*` (metadata only; no bodies; no mail-dir copy)
- Identities from `prefs.js` / `--identity` / `DATA_DUMPS_TB_IDENTITIES` for sent vs received
- Heuristic signals: newsletter, receipt, subscription, signup
- Explorer Thunderbird tab (ThirdStats/InboxPie-style volume, circadian, people, domains, folders, threads, signals)
- Patterns adapted from thunderbird-mcp (snapshot), third-stats / inboxpie (charts), email-archive-parser (heuristics)

### Browser history (Firefox Sky + legacy Chrome JSON)

- Sky History Export JSON (canonical) + one-time `history.json` merge → `browser.pages`
- URL-level grain; sensitive query params scrubbed; eTLD+1 via `tldextract` (offline PSL snapshot)
- Explorer Browser tab (scoreboard, domains/path tree, categories, search queries, forgotten/routines/comebacks, last-seen calendar, local hosts)
- Patterns adapted from chrome-history-explorer / 1History / BrowserHistoryVisualizer (queries only — still DuckDB + Marimo)
- **Later:** Firefox `places.sqlite` visit grain for circadian / research-session detection

### Amazon GDPR (multipart)

- Folder of `All Data Categories*.zip` → `amazon.*` (orders, searches, returns, media, Alexa structured, dump inventory)
- Voice WAVs inventory-only; cards/addresses/IPs/geolocation dropped; multi-currency spend (no FX merge)
- Explorer Amazon tab: footprint observatory, **marketplace country map**, spend/life chapters/types, search funnel, Alexa utterance Wrapped, Audible/Video

### Duolingo GDPR

- CSV zip → `duolingo.account|languages|leaderboards|inventory|friends|progress_events`
- Email/fullname/IPs/auth/ads/avatars/`payment_processor` dropped; tree progress blob kept as length only
- Explorer Duolingo tab (light LinkedIn/Ring-depth: scoreboard, XP, leagues, progress calendar, inventory)

### Uber GDPR

- Zip / `Uber Data/` folder → `uber.trips|order_items|ratings|support_messages`
- Profile/payments/saved locations/app GPS analytics dropped; trip coords + address strings + card numbers + Eats special instructions scrubbed (including `raw/uber/`)
- Explorer Uber tab: scoreboard, streaks, cities/products, **trip/Eats city maps** (static gazetteer — trip GPS scrubbed), circadian+calendar, forgotten/comeback cities, city-rank bump, fare×distance, Eats

### Google Takeout (multipart)

- Folder of `takeout-*.zip` → `google.*` (calendar, Play, maps saves/reviews, saved lists, photo metadata, My Activity, tasks, dump inventory)
- Access logs / mail mbox / contacts / Pay / GPS / street addresses / payment emails dropped; Photos+Drive media inventory-only
- Explorer Google tab: scoreboard (+hours/purchases/countries), streaks, life-chapters stack, calendar hours/stack/scatter/summary bump + timed vs all-day, circadian+calendar, photos calendar, maps country+reviews/ratings+forgotten/comebacks+bump, Play library/subscriptions + forgotten apps+purchases, activity action/product stack + title table (no URLs), tasks timeline, noise-calendar filter, footprint
- Local TZ: `Europe/Paris`; habit ICS epoch placeholders (`1970`) skipped at ingest

### Airbnb personal data

- HTML export zip (`Airbnb_data_request_*`) → `airbnb.account|reservations|searches|reviews|wishlists`
- Guest/host role from profile `id`; search-pin lat/lon kept for maps; street/Raw Location/Message/IPs/phones/KYC/payments dropped
- Explorer Airbnb tab: scoreboard, streaks, role/status/**place selectors**, **search pin map** + VAT-country choropleth, circadian + calendar, forgotten/comeback search places, place-rank bump, recent stays, reviews, wishlists
- Compare: reservations / accepted nights / searches totals + **search-place entity**; Correlations: same totals; Life rhythm preset includes `airbnb_searches` (+ `uber_trips`)
- Local TZ: `Europe/Paris`

### ChatGPT export

- Zip with `conversations-NNN.json` shards (+ shared / library / asset name map) → `chatgpt.account|conversations|messages|shared|assets`
- Message text kept; email/phone dropped; `.dat` / `chat.html` not copied into raw
- Explorer ChatGPT tab: period-compare scoreboard, streaks, model stack + rank bump, circadian + calendar, conversation scatter + click-lock, depth/length buckets, conversation flags, thinking/images + character series, content-type stack, forgotten/comebacks, reply latency, projects/GPTs, word clouds (user / assistant / bigrams / distinctive terms), shared + title tokens, assets metadata + monthly, optional narrative
- Compare / Correlations: messages + conversations; Compare entity = conversation
- Local TZ: `Europe/Paris`

### Tools — email index

- Explorer **Tools** tab lists every email address found in the exports: account fields the source tabs skip, other people's profiles and contacts, and addresses only mentioned in chats, tweets, subjects, or mail bodies
- One row per place (`mentioned in chat (4 mentions)`, `user profile · Ada`, `correspondent, from · Ada (12 messages)`)
- Source tables still have no email columns. Mail bodies are read from the Thunderbird index when it is on this machine and are not stored
- Cache: `$DATA_DUMPS_ROOT/warehouse/email_inventory.json` (outside git). Rebuilt when Tools opens after an export or the warehouse changes. `uv run email-inventory` prints counts only

### Tools — IP index

- Same **Tools** tab, under the email list. Login, session, device, and access-log addresses from the original exports the loaders skip. Not addresses mentioned in chats
- One row per place (`account login · PASSWORD`, `login audit`, `access log`, `session · Telegram macOS`)
- Source tables still have no IP columns. Uber analytics GPS is not plotted
- City, country, and ISP (GeoLite2 ASN organization) come from `$DATA_DUMPS_ROOT/warehouse/geoip/GeoLite2-City.mmdb` and `GeoLite2-ASN.mmdb` when you put them there. Private and documentation ranges are listed and left off the map
- Cache: `$DATA_DUMPS_ROOT/warehouse/ip_inventory.json` (outside git). Rebuilt when Tools opens after an export or either database changes. `uv run ip-inventory` prints counts only

### Compare tab (cross-source)

- Explorer **Compare** tab: pick source totals and entity/thread series (Telegram chat/reactions, Slack channel/person, LinkedIn conversation/connections/reactions/shares, Spotify artist/searches, Thunderbird contact/signals, Twitter account/DMs, Browser URLs last-seen / search URLs, Ring events/motion/app/flips, Sleep snore/noise, Amazon orders/searches/Alexa/Kindle/Audible/Video/Music, Slack active people, Duolingo progress/inventory/league/language, Uber trips/Eats/city, Google calendar/photos/maps/Play + calendar entity, Airbnb reservations/searches + place, ChatGPT messages/conversations + conversation, …)
- Monthly multiviewer overlay with each series as **% of its own max**; Pearson correlation heatmap on aligned shapes; raw values table alongside
- Series descriptors live in `contribution_series/` (one module per source; `make_compare_total` / `make_compare_entity` / `make_correlate_metric` helpers in `series_catalog.py`); catalogs merge from [`contributions.CONTRIBUTIONS`](../src/data_dumps/contributions.py)

### Correlations tab (cross-source)

- Explorer **Correlations** tab: daily-first Pearson matrix across source totals, top pairs (+ Spearman), focus scatter + z-score overlay, ±7 day lag scan
- Presets: Life rhythm / Comms / Sleep & body; monthly grain fallback; min-n gating; no zero-fill
- Metric descriptors merge from the same `CONTRIBUTIONS` registry (callable fetch; no warehouse column scan)

### Thin contribution registry

- Explicit `CONTRIBUTIONS` list bundles ingest `Source`, explorer gate/bounds, and Compare/Correlations series — one append per dump
- Prefer `series_catalog.make_*` factories for new totals; grain/agg stay human-chosen (no warehouse column auto-discovery)
- No dynamic discovery / entry points; panel imports stay lazy so `uv run ingest` does not pull Marimo

### Custom sources

- A folder or zip with `data_dumps.json` plus one CSV/JSON/JSONL file ingests into `custom.sources` / `custom.events` (time, optional entity, optional value). Email, IP, and phone columns are refused; other columns are not stored
- Explorer **Custom** tab: source picker, scoreboard, monthly, entity rank, forgotten / comeback, streaks, calendar, weekday × hour. Compare **Custom · events** and a per-source series; Correlations **Custom events**
- One explicit file `$DATA_DUMPS_ROOT/user_contributions.py` may append `Contribution`s (loader + optional panel). Imported by that path only — not entry points, not a directory scan. `detect` runs after built-ins. See [guides/services/custom.md](guides/services/custom.md)

### Dashboard upgrades from the open-source landscape

Query + chart + panel additions only (no new deps, no ingest restructuring). References: sleep_android_viz, Encore, Spotify-Unwrapped, TelAnalysis, ConvoMetrics.

- **Sleep:** compare-vs-previous scoreboard, regularity KPIs (bedtime/wake stddev, social jet lag, ≥7 h %), weekday × bedtime heatmap, monthly snore/noise, N-night actigraphy small multiples, Mi Band HR overlay + nightly avg HR vs hours, alarm-vs-wake histogram, late-evening Spotify × sleep (scatter + buckets)
- **Spotify:** milestones table, offline vs online, album depth score, longest listening sessions (30-min gap), top-artist rank movement vs previous window, artist monthly timeline (locked artist or top 3), "searched but barely played" (Account Data), **connection-country choropleth**
- **Telegram:** text KPIs, top words (en/it/es stopwords), emoji-in-text, message length you vs them, per-sender breakdown, reply Sankey (topic service parents excluded), aggregate-only "Narrate this view" (`telegram_queries.narrative_context`, never message text)
- **Geo maps (shared):** static city gazetteer + ISO country choropleths in `geo.py` / `explorer_panels.charts` — Uber trip/Eats cities, LinkedIn career locations, Ring device cities, Spotify conn_country, Amazon video/impressions country_code, Airbnb search pins (export lat/lon) + guest VAT country (no street addresses)

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
- `enrich-musicbrainz --dry-run`; CI (GitHub Actions + Gitea) runs tests + `marimo check`

## Later

- **Have I Been Pwned (potential)** — optional **Pwned** column on the Tools email table. Email breach search is not a free or open API: it needs a user-supplied subscription key (cheapest is Core, direct search, about $4.39/month billed annually, 10 requests per minute). Cache results next to `email_inventory.json` (outside git); never write them into source tables or commit the key. Off by default — the list includes other people's addresses, and a direct search sends the full address to HIBP. Hash-prefix email search (the address never leaves the machine) is Pro-only. The free test key only works on HIBP's published test accounts.
- **Password extractor (potential)** — Tools listing of passwords found in export credential files and account fields the loaders skip (browser saved logins, similar dumps), with where each one came from. Same boundary as the email index: not a source-table column, cache under the data root outside git, bodies and credential files not copied into `raw/`. Not a regex over chats. Optional check against the free [Pwned Passwords](https://haveibeenpwned.com/Passwords) API (k-anonymity, no key) — that answers “has this password appeared?”, not “has this address?”. Off by default.
- **Correlations tab configurability** — method picker (Pearson / Spearman / Kendall); rolling-window r; partial correlation; entity-level pairs; circadian/hour-bin correlations; zero-fill vs inner-join toggle; configurable min-n and lag range; optional aggregate-only LLM “Narrate top correlations”; share z-score/min-max helpers with Compare’s planned norm modes
- **Compare tab normalization modes** — min–max [0,1], z-score, absolute small-multiples; make the mode selectable in the UI (today: % of series max only)
- **GUI-driven operations** — eventually all warehouse actions from the Marimo dashboard: ingest, MusicBrainz enrich, re-ingest, and LLM setup — not only explore/filter/narrate. Today ingest and enrich are CLI-only because DuckDB is single-writer; a GUI path needs an orchestration layer (stop dashboard → run job → reopen, or a dedicated writer service) without asking the user to juggle terminals. See [WAREHOUSE.md](WAREHOUSE.md) for current constraints.
- Wikidata P136 genre enrichment (deferred; MusicBrainz tags only today)

- Other GDPR / export sources when a dump is in hand (ingest + explorer tab via [add-a-dump](guides/add-a-dump.md)):
  - **Reddit** — posts, comments, votes, saved; messaging if present
  - **Airbnb** — stays, host/guest messages, searches
  - **Booking.com** — bookings, searches, messages
  - **WhatsApp** — chat export (text + relative media paths; no phonebook dump by default)
  - **GitHub** — contributions, issues/PRs, starred repos (account export or API archive — prefer dump-only)
- Cover Art Archive images after MusicBrainz
- LiteLLM sidecar in compose (TranscriptX-style gateway)
- Chat-over-corpus / RAG over every play

## Non-goals

- Spotify Web API enrichment
- Cloud LLM as silent default
- Last.fm (account deleted)
- **Mi Band beyond the shipped one-off** — no new metrics, devices, or explorer investment; Sleep may keep using existing `miband.heart_rate` when present
- Hosted multi-user SaaS
- Dynamic plugin discovery (setuptools entry points, auto-import of every module, scanning a plugins directory). Built-in dumps stay on the thin `CONTRIBUTIONS` list. The single file `$DATA_DUMPS_ROOT/user_contributions.py` may append contributions; it is loaded by path, not discovered
- Warehouse column auto-discovery as Compare/Correlations catalog (grain/agg still human-chosen descriptors)

## Related

| Doc | Role |
|-----|------|
| [README.md](../README.md) | Setup, Docker, privacy |
| [WAREHOUSE.md](WAREHOUSE.md) | **Single-writer lock** — UI vs ingest vs enrich |
| [guides/getting-your-data.md](guides/getting-your-data.md) | Export index; per-service pages under [guides/services/](guides/services/) |
| [guides/add-a-dump.md](guides/add-a-dump.md) | **Add a dump** checklist (Source + explorer); agents start here |
| [../AGENTS.md](../AGENTS.md) | Agent entrypoint |
| [../assessments/dashboard-depth-2026-09.md](../assessments/dashboard-depth-2026-09.md) | Explorer depth scorecard |
| [../notebooks/explorer.py](../notebooks/explorer.py) | Combined Marimo dashboard (Correlations + Compare + Spotify / Telegram / LinkedIn / Twitter / Slack / Browser / Sleep / Mi Band / …) |
| [../notebooks/spotify.py](../notebooks/spotify.py) | Spotify-only notebook |
| [../notebooks/telegram.py](../notebooks/telegram.py) | Telegram-only notebook |
| [../notebooks/sleep.py](../notebooks/sleep.py) | Sleep-only notebook (thin wrapper over `render_sleep_panel`) |
| [../notebooks/linkedin.py](../notebooks/linkedin.py) | LinkedIn-only notebook |
| [../notebooks/twitter.py](../notebooks/twitter.py) | Twitter-only notebook |
