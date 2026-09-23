# Cursor History — ingest & dashboard plan

**Status:** Phase 1–3 core landed (ingest + Wrapped explorer + text search + prompt-quality proxies + secret redaction). Live `state.vscdb` path still deferred.  
**Date:** 2026-09-23  
**Fits:** existing `data_dumps` pattern (DuckDB warehouse under `DATA_DUMPS_ROOT`, Marimo explorer, explicit `Contribution` registration). Companion: [add-a-dump.md](guides/add-a-dump.md), [WAREHOUSE.md](WAREHOUSE.md), ChatGPT peer [guides/services/chatgpt.md](guides/services/chatgpt.md). Service page: [guides/services/cursor_history.md](guides/services/cursor_history.md).

---

## 1. Source of truth

| Layer | Path | Role |
|-------|------|------|
| **Primary portable export** | `/Users/89298/Desktop/cursor-history-export/` | Snapshot produced by `cursor-history` (Markdown + JSON session files, Composer backup zip when feasible, agent-transcript tree copy, `composer-headers-inventory.json`) |
| **Live Composer / global KV** | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` (+ WAL/SHM) | Canonical Composer sessions (`composerHeaders`, `cursorDiskKV` keys `composerData:*`, `bubbleId:*`, …). On this machine ~30 GB / ~5k composers / ~670k bubbles — slow to scan. |
| **Live workspace DBs** | `~/Library/Application Support/Cursor/User/workspaceStorage/*/state.vscdb` | Per-workspace Composer bindings (~hundreds of MB total here). |
| **Live Agent transcripts** | `~/.cursor/projects/*/agent-transcripts/**/*.jsonl` | Agent chat + tool calls (JSONL). Fast to copy; partial overlap with Composer. |
| **Live Store / CLI / ACP** | `~/.cursor/chats/**/store.db`, `~/.cursor/acp-sessions/**/store.db` | Present when used; none found on this machine at plan time. |

**Ingest should prefer the Desktop export** (stable, offline, no lock fights with Cursor). Live paths are for incremental refresh and for sessions missing from an incomplete export.

Tool: [`cursor-history`](https://github.com/S2thend/cursor-history) (`npm i -g cursor-history`). Re-export recipe lives in the Desktop `EXPORT_MANIFEST.md`.

---

## 2. Proposed layout under `DATA_DUMPS_ROOT`

Default root: `~/Documents/data_dumps_raw` (never git). Suggested tree:

```text
$DATA_DUMPS_ROOT/
  raw/cursor_history/                    # owned copy after ingest detect()
    manifest.json                        # export date, tool version, commands, counts
    markdown/                            # *.md from cursor-history export --all -f md
    json/                                # *.json from export --all -f json
    agent-transcripts/<project-slug>/    # copied jsonl trees
    backup/*.zip                         # Composer-only backup if present
    composer-headers-inventory.json      # optional fast index from composerHeaders
  warehouse/catalog.duckdb               # schema cursor_history.*
```

Point ingest at the Desktop folder **or** a copy under `raw/cursor_history/` after the first successful load (same pattern as Thunderbird / multipart Amazon: loader copies keep-list into `raw_dir(slug)`).

**Slug:** `cursor_history` (underscore to match DuckDB schema naming peers).

---

## 3. Schema (DuckDB)

Grain and tables (names illustrative; finalize in loader + forbidden-column tests):

### `cursor_history.sessions`

One row per logical session.

| Column | Notes |
|--------|--------|
| `session_id` | UUID (Composer / transcript id); **dedup key** |
| `source_kind` | `composer` \| `agent_transcript` \| `store` \| `merged` |
| `title` | From export / headers |
| `workspace_id` | Cursor workspaceStorage hash when known |
| `workspace_path` | Resolved path if present in export metadata |
| `project_slug` | e.g. `Users-89298-Documents-data-dumps` from transcript path |
| `created_at`, `updated_at` | UTC timestamptz; also `year` / `month` / local wall-clock (`Europe/Paris` — peer of ChatGPT) |
| `is_subagent`, `subagent_type` | From `composerHeaders` |
| `is_archived` | |
| `message_count`, `tool_call_count` | Derived |
| `model_primary` | Mode / most-used model slug if available |
| `export_path` | Relative path under `raw/cursor_history/` |
| `content_sha256` | Hash of canonical JSON body for idempotent reload |

**Dedup key:** `session_id` (logical). On conflict, keep newer `updated_at` / larger `content_sha256` change; record `source_kind` precedence: prefer richer `merged`/`composer` over transcript-only when both exist for the same UUID.

### `cursor_history.messages`

Grain: `(session_id, message_id)` — stable id from export JSON when present; else synthetic `{session_id}:{ordinal}` with `id_provenance = synthetic`.

| Column | Notes |
|--------|--------|
| `session_id`, `message_id`, `ordinal` | |
| `role` | `user` \| `assistant` \| `tool` \| `thinking` \| `error` \| … |
| `created_at` | stored vs inferred flag if export provides provenance |
| `model` | per-message when present |
| `text` | Full text (product is messaging — OK per add-a-dump; still never commit raw) |
| `token_estimate` | Optional heuristic for volume charts |
| `has_diff`, `has_thinking` | Booleans |

### `cursor_history.tool_calls`

Grain: `(session_id, tool_call_id)` or `(session_id, message_id, ordinal)`.

| Column | Notes |
|--------|--------|
| `tool_name`, `status` | |
| `args_json` / `result_summary` | Prefer truncated summary in warehouse if args contain secrets; full args only in raw files |
| `duration_ms` | When available |

### `cursor_history.models` (optional dim)

Distinct model slugs + first/last seen + message counts — safe aggregate for Compare/Correlations.

### Idempotent reload

1. `detect(path)` — true if folder contains `EXPORT_MANIFEST.md` / `composer-headers-inventory.json` / `markdown|json` session files / agent-transcripts tree, or a zip shaped like a `cursor-history` backup.
2. `load(path, conn)` — `CREATE SCHEMA IF NOT EXISTS cursor_history`; **replace** tables owned by this slug (or delete-by-`session_id` set then insert) so re-ingest is safe.
3. Copy keep-list into `raw/cursor_history/` once; do not duplicate 30 GB live `state.vscdb` into raw.
4. Inventory CLI summary: session count by `source_kind`, date range, approx message rows.

---

## 4. What NOT to commit vs safe derivatives

**Never commit (already covered by `.gitignore` patterns for dumps / duckdb / parquet):**

- Raw Markdown/JSON session bodies, agent JSONL, Composer backup zips
- Anything under `~/Documents/data_dumps_raw/`
- Desktop export folder
- Live `state.vscdb` copies

**Why:** chats routinely contain API keys, `.env` snippets, private URLs, personal data, unpublished code.

**Safe / OK in git:** this plan, synthetic fixtures under `tests/`, loader/query/panel **code**, empty schema docs.

**Safe derived aggregates (warehouse OK; still local-only):**

- Counts by day/week, model mix, workspace mix, tool-name histograms
- Session title tokens / anonymized n-grams (optional; treat like ChatGPT word clouds)
- Prompt-length buckets, session duration proxies
- **Do not** put emails/IPs on source tables — register `TextScan`s in Tools/`email_inventory` if scanning message text for addresses
- LLM narratives: aggregates only (`narrative_context`), never raw prompts/rows

---

## 5. Dashboard (Marimo — match repo stack)

**Stack:** DuckDB + existing `uv run marimo run notebooks/explorer.py` + `explorer_panels/cursor_history.py` + `cursor_history_queries.py` + `Contribution` entry. No new web framework. Bind `127.0.0.1` only.

**Views / pages (Cursor History tab):**

1. **Session list** — filter by date, workspace/project, source_kind, subagent; click → message transcript (virtualized / truncated in UI).
2. **Search** — DuckDB `ILIKE` / FTS on `messages.text` + titles (phase 3); highlight hits.
3. **Volume over time** — messages/sessions per day; model stack; tool-call volume.
4. **Prompt-quality later** — deferred metrics (length, follow-ups, edit/tool density); not phase 1.
5. Optional **Compare** series — daily message count / session count via `contribution_series` (phase 2+).

Closest peer UX: ChatGPT tab (conversation list + scoreboard + circadian).

---

## 6. Incremental update path

| Mode | When | How |
|------|------|-----|
| **A. Re-export** | Periodic / after big Cursor use | `cursor-history export --all -f md|json -o …` (+ optional `backup`); re-run `uv run ingest` on the Desktop (or copied) folder. Idempotent by `session_id` + `content_sha256`. |
| **B. Transcripts only** | Fast delta | Rsync/copy new `agent-transcripts/**/*.jsonl`; ingest merges by session id. |
| **C. Live `state.vscdb`** | When export incomplete or too slow | Optional reader path: open DB read-only, stream `composerHeaders` + selected `composerData`/`bubbleId` keys. **Stop Marimo first** if writing warehouse; avoid long locks while Cursor is writing WAL. Prefer export/backup over live read for v1. |
| **D. Composer backup zip** | Disaster recovery | `cursor-history backup -o …`; ingest can treat backup as source via `cursor-history` library/`--backup` or by extracting then loading JSON exports. Note: backup is Composer-only (~size of global DB). |

**Operational constraint:** global `state.vscdb` ~30 GB on this machine — full live scan and full dual-format export need raised `--source-limit`s, lots of disk headroom, and patience. Disk free space must exceed backup size before `backup`.

---

## 7. Open questions

1. **Timezone:** default `Europe/Paris` (ChatGPT peer) vs `Europe/Rome` (majority of sources)?
2. **Merge policy** when Composer + agent transcript share a UUID but diverge in content — which wins for `messages.text`?
3. **Subagents:** separate sessions in UI vs nest under parent composer?
4. **Secret redaction at ingest?** Strip `sk-`, `ghp_`, PEM blocks into `redacted` markers, or leave raw under `raw/` only and accept warehouse text risk on localhost?
5. **Store/ACP:** implement stubs now or wait until those trees appear locally?
6. **FTS:** DuckDB FTS extension vs external index for phase-3 search?
7. **Export completeness:** if `export --all` cannot finish within disk/time budget, is transcript+headers inventory an acceptable phase-1 corpus?

---

## 8. Phased build order

### Phase 1 — Ingest only

- [x] `sources/cursor_history.py` (`detect` / `load` / `tables` / `inventory`)
- [x] Register `Contribution` (ingest-only tab deferred or minimal)
- [x] Synthetic mini export fixture + `tests/test_cursor_history_ingest.py` (forbidden columns: no email/IP columns)
- [x] Docs: `guides/services/cursor_history.md` + index row in `getting-your-data.md`
- [x] Load Desktop export into `cursor_history.sessions|messages|tool_calls`
- [x] Confirm inventory counts vs `EXPORT_MANIFEST.md` (5,878 sessions match composer export; ~669k messages ≈ bubble scale)

### Phase 2 — Browse UI

- [x] `cursor_history_queries.py` + `explorer_panels/cursor_history.py`
- [x] Session list + detail + volume scoreboard / circadian
- [x] Wire explorer tab; panel smoke tests
- [x] Optional Compare totals

### Phase 3 — Search (+ prompt-quality later)

- [x] Full-text search UI over messages (bound `contains` / ILIKE substring; DuckDB FTS extension still optional later)
- [x] Prompt-quality / depth metrics (length buckets, session depth, tool density, reply latency)
- [x] Incremental path B documented in WAREHOUSE.md (re-export + transcript rsync; live DB still deferred)
- [x] ROADMAP **Shipped** bullet
- [x] Warehouse secret redaction (`sk-` / `ghp_` / PEM / …); rematerialize skip when source path unchanged
- [x] Tool family stack + rank bump; unified mode / subagent mix

---

## 9. Non-goals (this plan)

- Implementing loader or dashboard code in the same change as this doc  
- Committing or pushing any export  
- Hosting the dashboard beyond loopback  
- Restoring Composer history into Cursor from the warehouse (use `cursor-history restore` on backup zips instead)
