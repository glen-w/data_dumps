# Cursor History

Index: [Getting your data](../getting-your-data.md). Plan: [cursor-history-ingest-dashboard.md](../../cursor-history-ingest-dashboard.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `cursor_history` | `Europe/Paris` | Cursor tab |

## Request

Not a company DSAR. Build a portable snapshot of local Cursor Composer + Agent transcripts with [`cursor-history`](https://github.com/S2thend/cursor-history) (or the Desktop `direct_export.py` workaround when the CLI stalls on a huge `state.vscdb`). Typical layout:

- `EXPORT_MANIFEST.md`
- `json/` — one Composer session JSON per file
- `agent-transcripts/` — copied `~/.cursor/projects/*/agent-transcripts/**/*.jsonl`
- `composer-headers-inventory.json` (optional but useful)

Do **not** point ingest at the live `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` (~tens of GB). Prefer the Desktop export folder.

## Ingest

```bash
uv run ingest /Users/89298/Desktop/cursor-history-export
```

**Kept.** Session metadata, message text (with common secret shapes redacted in the warehouse), truncated tool args/results, agent transcript tool_use names. Grain: sessions by `session_id`; messages by `(session_id, message_id)`; tool calls by `(session_id, tool_call_id)`. Composer wins over agent transcript when the same UUID appears in both (`source_kind` may become `merged`); overlapping transcript message bodies are skipped.

**Dropped / not copied.** Live `state.vscdb`, redundant `markdown/` (JSON is enough), Composer backup zips, logs/pids. No email/IP columns on source tables (Tools tab scans `messages.text`). Warehouse redacts `sk-` / `ghp_` / PEM / similar; raw export files under `raw/cursor_history/` stay as exported.

**Explorer.** Cursor tab — scoreboard (+ depth / tool density), streaks, volume, tool family stack + rank bump, mode/project mix, prompt length + session depth, reply latency, circadian + calendar, message text search, session list + click-lock transcript, scatter, forgotten/comebacks, optional narrative. Compare / Correlations: messages + sessions.

## Refresh

Prefer re-export then re-ingest (idempotent). After the first load, pointing ingest at the Desktop folder again skips rematerialize when `raw/cursor_history/source_path.txt` still matches. Transcript-only deltas: copy new `agent-transcripts/**/*.jsonl` into the export (or raw tree) and re-run ingest. Do not open live `state.vscdb` for v1.
