# Add a dump

Hygiene list for **humans and agents**. Work top to bottom. Skip a step only when it does not apply, and say so in the PR / session note.

This is the path for a **new** personal export (GDPR zip, app CSV, mail profile, browser history, …). Updating charts on an already-shipped source is ordinary query/panel work — not this guide.

Numbered registration points, privacy defaults, docs in the same session — no improvised shorter path.

Standing ops: [WAREHOUSE.md](../WAREHOUSE.md) (single-writer). Direction: [ROADMAP.md](../ROADMAP.md). Depth bar: [assessments/dashboard-depth-2026-09.md](../../assessments/dashboard-depth-2026-09.md). Protocol: [`Source`](../../src/data_dumps/sources/base.py).

**Copy-from templates (pick the closest):**

| Shape | Prefer reading |
|-------|----------------|
| CSV / one file | [`sources/sleep.py`](../../src/data_dumps/sources/sleep.py) or [`sources/linkedin.py`](../../src/data_dumps/sources/linkedin.py) |
| Nested JSON zip | [`sources/telegram.py`](../../src/data_dumps/sources/telegram.py) / [`sources/slack.py`](../../src/data_dumps/sources/slack.py) |
| Multipart GDPR folder | [`sources/amazon.py`](../../src/data_dumps/sources/amazon.py) / [`sources/ring.py`](../../src/data_dumps/sources/ring.py) |
| External DB snapshot | [`sources/thunderbird.py`](../../src/data_dumps/sources/thunderbird.py) |
| Thin explorer wiring | LinkedIn / Sleep panels in [`explorer_panels/<slug>.py`](../../src/data_dumps/explorer_panels/) + [`notebooks/explorer.py`](../../notebooks/explorer.py) |
| Full Wrapped explorer | Spotify / Telegram / Slack (queries + panel + narrative) |

## Do not

- Commit dumps, extracted JSON/CSV, DuckDB files, `.env`, or media bytes. Data lives under `~/Documents/data_dumps_raw` (`DATA_DUMPS_ROOT`), outside git.
- Run `ingest` / enrich while Marimo (or `docker compose up app`) holds the warehouse. Stop the dashboard first — [WAREHOUSE.md](../WAREHOUSE.md).
- Load IPs, emails, phones, payment instruments, KYC / ads / inference blobs, precise home addresses, or Wi‑Fi SSIDs **by default**. Drop at ingest; keep a forbidden-column test. Message text is OK when the product is messaging (Telegram, Slack, LinkedIn, Twitter) — document it.
- Invent a **dynamic** plugin registry (entry points, auto-import of every module). Use the thin explicit [`CONTRIBUTIONS`](../../src/data_dumps/contributions.py) list instead — one append per dump.
- Ship an explorer tab with only a raw table and call it done. Aim for the Wrapped checklist (below) unless the dump is ingest-only for now.
- Expand **Mi Band** — frozen one-off; Sleep may keep using `miband.heart_rate` when present.
- Put LLM prompts on raw rows. Narrate aggregates only (`narrative_context` dicts).
- Run Black/Ruff on `notebooks/` — Marimo cell structure is not a formatter target.
- Guess timezone or “me” identity. Use an explicit local TZ (usually `Europe/Rome` / `Europe/London` as peers do) and document how sent-vs-received / is_from_me is derived.

---

## Checklist

Copy into a session note and tick as you go.

### 0. Decide

- [ ] **Dump in hand?** Do not scaffold against a fictional export. Open the zip/folder and list real filenames.
- [ ] **Slug:** lowercase, no spaces (`reddit`, `ring`, `github`) — matches schema name + `raw/<slug>/`.
- [ ] **Lane:**
  - **Ingest-only** — tables + CLI + tests; no explorer yet (valid; Ring is here).
  - **Explorer** — queries + Marimo tab in the same effort when the dump is the point of the work.
- [ ] **Grain:** what is one row? (`slack.messages` = channel_id+ts; `telegram.messages` = chat_id+message_id; `browser.pages` = URL last-seen; …). Write it down before coding.
- [ ] **Privacy keep/drop list:** columns/files kept vs dropped. Put dropped names in tests.
- [ ] **Timezone / “me”:** local wall-clock TZ; how we know outbound vs inbound.
- [ ] **Cross-source joins?** Only if another schema already exists (e.g. Sleep × Mi Band). Prefer optional `has_table` gates.
- [ ] **Roadmap:** tick or add a [ROADMAP.md](../ROADMAP.md) shipped bullet when done; do not invent backlog for frozen sources.

### 1. Source loader

- [ ] Add [`src/data_dumps/sources/<slug>.py`](../../src/data_dumps/sources/) implementing [`Source`](../../src/data_dumps/sources/base.py):
  - `name` — slug string
  - `detect(path)` — true only for this export (reject unrelated zips)
  - `load(path, conn)` — create schema/tables; prefer replace-or-create clear ownership of `slug.*`
  - `tables()` — qualified names `slug.table`
  - `inventory(conn)` — dict with `summary` string for CLI
- [ ] Copy keep-list files into `raw_dir(slug)` (via [`paths.raw_dir`](../../src/data_dumps/paths.py)); never copy PII files you intend to drop.
- [ ] Media / attachments: leave bytes on disk; store relative paths or metadata only (Telegram/Slack pattern).
- [ ] Derive `year` / `month` / local timestamps when time series matter (explorer filters are year-based).

### 2. Register contribution

- [ ] Export from [`sources/__init__.py`](../../src/data_dumps/sources/__init__.py).
- [ ] Append one [`Contribution(...)`](../../src/data_dumps/contributions.py) to `CONTRIBUTIONS` (detect order matters for overlapping `detect` — be specific). This derives `ingest.SOURCES`, explorer tab presence/bounds, and Compare/Correlations catalogs. Explorer tabs use plain `tab_label` plus a Lucide `tab_icon` (`lucide:…`); the notebook renders via `mo.icon`.
- [ ] Define callable series/metrics in [`contribution_series.py`](../../src/data_dumps/contribution_series.py) (prefer `make_compare_total` / `make_correlate_metric` / `make_compare_entity` from [`series_catalog.py`](../../src/data_dumps/series_catalog.py); or import tuples into the Contribution). Choose grain and aggregation explicitly — do not scan warehouse columns.
- [ ] `pick_source` smoke: synthetic mini dump → correct `source.name`.

### 3. Tests (synthetic fixtures only)

- [ ] `tests/test_<slug>_ingest.py` — `make_mini_…` fixture in-repo (no real dump).
- [ ] `detect` yes / unrelated no.
- [ ] `load` row counts + **forbidden columns / values** assertions.
- [ ] CLI: `main([str(path), "--db", …]) == 0` optional but preferred.
- [ ] Query smoke when explorer ships (`tests/test_<slug>_queries.py` or extend ingest test).

### 4. Queries (explorer lane)

- [ ] [`src/data_dumps/<slug>_queries.py`](../../src/data_dumps/) with:
  - `FilterState` + `chip_labels`
  - `data_bounds(conn)` → at least `min_year`, `max_year`, `first_day`, `last_day`
  - `filter_from_widgets(...)`
  - `scoreboard` (prefer `compare_previous=`)
  - Domain analyses — start from the Wrapped bar below
- [ ] No SQL string interpolation of user text; bind parameters (Thunderbird contact search pattern).

### 5. Explorer panel + notebook

Marimo rule: **do not** read `widget.value` in the cell that created the widget. Pattern in [`explorer_panels/<slug>.py`](../../src/data_dumps/explorer_panels/):

1. `make_<slug>_controls` — widgets + `mo.state` locks (always runs)
2. `render_<slug>_panel` — read values, query, return one `mo.vstack` (leaf; inactive tab gated with `mo.stop` in `explorer.py`)

- [ ] `Controls` dataclass + `make_*_controls` + `render_*_panel` in `explorer_panels/<slug>.py`
- [ ] Wire [`notebooks/explorer.py`](../../notebooks/explorer.py): controls cell + render cell (presence/tabs come from `CONTRIBUTIONS`; keep Marimo create-vs-read cells separate)
- [ ] Optional thin standalone `notebooks/<slug>.py` wrapping the panel (LinkedIn/Sleep/Twitter style) — not required for every source
- [ ] Panel smoke in [`tests/test_explorer_panels.py`](../../tests/test_explorer_panels.py)

### 6. Document (same session)

- [ ] README section: how to ingest (stop dashboard → `uv run ingest …` → reopen), tables, privacy drops, explorer blurb
- [ ] [WAREHOUSE.md](../WAREHOUSE.md) ingest subsection if the path is non-obvious (Thunderbird profile, multipart Amazon, …)
- [ ] [ROADMAP.md](../ROADMAP.md) **Shipped** bullet (format match peers)
- [ ] Layout tree under README if a new `raw/<slug>/` appears
- [ ] Privacy paragraph if keep/drop differs from defaults

### 7. Prove locally

- [ ] Stop dashboard
- [ ] `uv run ingest ~/Documents/data_dumps_raw/<…>`
- [ ] Inventory summary looks right
- [ ] `uv run pytest` (at least new tests + explorer panel if any)
- [ ] `uv run ruff check` / `black --check` / `mypy` on touched `src` + `tests`
- [ ] Reopen explorer; tab appears; charts render without errors

---

## Wrapped checklist (explorer depth)

Peers (Spotify / Telegram / Twitter / Slack) set the bar. New explorers should hit as many as the data allows:

| Pattern | Notes |
|---------|--------|
| Period-compare scoreboard | Equal-length previous year window |
| Streaks | Domain-appropriate (active days, ≥threshold, …) |
| Circadian + calendar | Weekday×hour and daily heatmap |
| Forgotten + comeback | Entity silent for N years / returned after gap |
| Bump **or** scatter/index | Rank movement or behavioral 2D view |
| Filters / click-to-lock | Year range minimum; entity lock when there is a natural unit |
| Narrative (optional) | Aggregates-only via `llm_client.narrate` |

Do not match Amazon’s multi-surface breadth on day one. Prefer pattern completeness over table count. Depth audit: [assessments/dashboard-depth-2026-09.md](../../assessments/dashboard-depth-2026-09.md).

---

## Registration map (files)

| Concern | Where |
|---------|--------|
| Protocol | `src/data_dumps/sources/base.py` |
| Loader | `src/data_dumps/sources/<slug>.py` |
| Package export | `src/data_dumps/sources/__init__.py` |
| **Contribution registry** | `src/data_dumps/contributions.py` → `CONTRIBUTIONS` (ingest + tab gate + series) |
| Series descriptors | `src/data_dumps/contribution_series.py` + `series_catalog.py` |
| CLI | `src/data_dumps/ingest.py` (uses `contributions.SOURCES`) |
| Data paths | `src/data_dumps/paths.py` → `raw/<slug>/`, shared `warehouse/catalog.duckdb` |
| Queries | `src/data_dumps/<slug>_queries.py` |
| UI builders | `src/data_dumps/explorer_panels/<slug>.py` (+ package `__init__` re-exports) |
| Combined dashboard | `notebooks/explorer.py` |
| Ingest tests | `tests/test_<slug>_ingest.py` |
| Query / panel tests | `tests/test_<slug>_queries.py`, `tests/test_explorer_panels.py` |
| Human docs | `README.md`, `docs/WAREHOUSE.md`, `docs/ROADMAP.md` |

---

## Schema and naming conventions

- DuckDB **schema = slug** (`linkedin.messages`, not `main.linkedin_messages`).
- Prefer UTC + local timestamp columns (`ts_utc` / `ts_local` or `date_utc` / `date_local`) plus `year` for filters.
- `inventory()["summary"]` should be one CLI-readable line (row counts + date span).
- Additive siblings in the same schema are OK when they must not clobber a primary table (Spotify Account Data vs `spotify.plays`).
- Conditional explorer sections: `has_table(conn, …)` — never require optional enrichments.

---

## README source blurb shape

```markdown
## <Product> export

Stop the dashboard first ([WAREHOUSE.md](docs/WAREHOUSE.md)).

```bash
uv run ingest ~/Documents/data_dumps_raw/<slug>/<file-or-folder>
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

- Tables: `slug.…` (grain in one clause)
- Dropped at ingest: …
- Explorer: … tab (scoreboard, …)   # omit if ingest-only
```

---

## Agent extras

- Read **this** guide before writing a new `sources/*.py` or explorer tab. Companion rule: [`.cursor/rules/add-dump.mdc`](../../.cursor/rules/add-dump.mdc).
- Do not invent dump layouts. If the export is not on disk, stop and ask.
- Prefer extending the closest existing source over novel frameworks.
- Session is incomplete until tests + README/ROADMAP (and explorer wiring if that was the lane) are done.
- Never commit warehouse or `data_dumps_raw` contents.
