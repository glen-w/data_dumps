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
- Explorer Amazon tab: footprint observatory, spend/life chapters/types, search funnel, Alexa utterance Wrapped, Audible/Video

### Duolingo GDPR

- CSV zip → `duolingo.account|languages|leaderboards|inventory|friends|progress_events`
- Email/fullname/IPs/auth/ads/avatars/`payment_processor` dropped; tree progress blob kept as length only
- Explorer Duolingo tab (light LinkedIn/Ring-depth: scoreboard, XP, leagues, progress calendar, inventory)

### Compare tab (cross-source)

- Explorer **Compare** tab: pick source totals and entity/thread series (Telegram chat, Slack channel/person, LinkedIn conversation, Spotify artist, Thunderbird contact, Twitter account, Browser URLs last-seen / search URLs, Ring events / flips, Sleep snore/noise, Amazon Alexa/Kindle, Slack active people, …)
- Monthly multiviewer overlay with each series as **% of its own max**; Pearson correlation heatmap on aligned shapes; raw values table alongside
- Series descriptors live in `contribution_series.py` (`make_compare_total` / `make_compare_entity` / `make_correlate_metric` helpers in `series_catalog.py`); catalogs merge from [`contributions.CONTRIBUTIONS`](../src/data_dumps/contributions.py)

### Correlations tab (cross-source)

- Explorer **Correlations** tab: daily-first Pearson matrix across source totals, top pairs (+ Spearman), focus scatter + z-score overlay, ±7 day lag scan
- Presets: Life rhythm / Comms / Sleep & body; monthly grain fallback; min-n gating; no zero-fill
- Metric descriptors merge from the same `CONTRIBUTIONS` registry (callable fetch; no warehouse column scan)

### Thin contribution registry

- Explicit `CONTRIBUTIONS` list bundles ingest `Source`, explorer gate/bounds, and Compare/Correlations series — one append per dump
- Prefer `series_catalog.make_*` factories for new totals; grain/agg stay human-chosen (no warehouse column auto-discovery)
- No dynamic discovery / entry points; panel imports stay lazy so `uv run ingest` does not pull Marimo

### Dashboard upgrades from the open-source landscape

Query + chart + panel additions only (no new deps, no ingest restructuring). References: sleep_android_viz, Encore, Spotify-Unwrapped, TelAnalysis, ConvoMetrics.

- **Sleep:** compare-vs-previous scoreboard, regularity KPIs (bedtime/wake stddev, social jet lag, ≥7 h %), weekday × bedtime heatmap, monthly snore/noise, N-night actigraphy small multiples, Mi Band HR overlay + nightly avg HR vs hours, alarm-vs-wake histogram, late-evening Spotify × sleep (scatter + buckets)
- **Spotify:** milestones table, offline vs online, album depth score, longest listening sessions (30-min gap), top-artist rank movement vs previous window, artist monthly timeline (locked artist or top 3), "searched but barely played" (Account Data)
- **Telegram:** text KPIs, top words (en/it/es stopwords), emoji-in-text, message length you vs them, per-sender breakdown, reply Sankey (topic service parents excluded), aggregate-only "Narrate this view" (`telegram_queries.narrative_context`, never message text)

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

- **Correlations tab configurability** — method picker (Pearson / Spearman / Kendall); rolling-window r; partial correlation; entity-level pairs; circadian/hour-bin correlations; zero-fill vs inner-join toggle; configurable min-n and lag range; optional aggregate-only LLM “Narrate top correlations”; share z-score/min-max helpers with Compare’s planned norm modes
- **Compare tab normalization modes** — min–max [0,1], z-score, absolute small-multiples; make the mode selectable in the UI (today: % of series max only)
- **GUI-driven operations** — eventually all warehouse actions from the Marimo dashboard: ingest, MusicBrainz enrich, re-ingest, and LLM setup — not only explore/filter/narrate. Today ingest and enrich are CLI-only because DuckDB is single-writer; a GUI path needs an orchestration layer (stop dashboard → run job → reopen, or a dedicated writer service) without asking the user to juggle terminals. See [WAREHOUSE.md](WAREHOUSE.md) for current constraints.
- Wikidata P136 genre enrichment (deferred; MusicBrainz tags only today)

- Other GDPR sources (Reddit) when a dump is in hand
- Cover Art Archive images after MusicBrainz
- LiteLLM sidecar in compose (TranscriptX-style gateway)
- Chat-over-corpus / RAG over every play

## Non-goals

- Spotify Web API enrichment
- Cloud LLM as silent default
- Last.fm (account deleted)
- **Mi Band beyond the shipped one-off** — no new metrics, devices, or explorer investment; Sleep may keep using existing `miband.heart_rate` when present
- Hosted multi-user SaaS
- Dynamic plugin discovery (setuptools entry points, auto-import of every module) — thin explicit `CONTRIBUTIONS` only
- Warehouse column auto-discovery as Compare/Correlations catalog (grain/agg still human-chosen descriptors)

## Related

| Doc | Role |
|-----|------|
| [README.md](../README.md) | Setup, Docker, privacy |
| [WAREHOUSE.md](WAREHOUSE.md) | **Single-writer lock** — UI vs ingest vs enrich |
| [guides/add-a-dump.md](guides/add-a-dump.md) | **Add a dump** checklist (Source + explorer); agents start here |
| [../AGENTS.md](../AGENTS.md) | Agent entrypoint |
| [../assessments/dashboard-depth-2026-09.md](../assessments/dashboard-depth-2026-09.md) | Explorer depth scorecard |
| [../notebooks/explorer.py](../notebooks/explorer.py) | Combined Marimo dashboard (Correlations + Compare + Spotify / Telegram / LinkedIn / Twitter / Slack / Browser / Sleep / Mi Band / …) |
| [../notebooks/spotify.py](../notebooks/spotify.py) | Spotify-only notebook |
| [../notebooks/telegram.py](../notebooks/telegram.py) | Telegram-only notebook |
| [../notebooks/sleep.py](../notebooks/sleep.py) | Sleep-only notebook (thin wrapper over `render_sleep_panel`) |
| [../notebooks/linkedin.py](../notebooks/linkedin.py) | LinkedIn-only notebook |
| [../notebooks/twitter.py](../notebooks/twitter.py) | Twitter-only notebook |
