# Ollama

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `ollama` | `Europe/Paris` | Ollama tab |

## Request

Not a company DSAR. The Ollama app keeps chats in a local SQLite file:

- macOS: `~/Library/Application Support/Ollama/db.sqlite` (plus `db.sqlite-wal`)
- Linux: `~/.ollama/db.sqlite`
- Windows: `%LOCALAPPDATA%\Ollama\db.sqlite`

`~/.ollama` on macOS is models, logs, and a key. Do not point ingest at that directory unless it actually contains the chat `db.sqlite`.

## Ingest

```bash
uv run ingest "$HOME/Library/Application Support/Ollama"
```

Stop the dashboard first. The loader snapshots the database (the app can stay open) and writes JSONL under `raw/ollama/`. A later ingest can use that folder. The SQLite file itself is not copied.

**Kept.** Chat titles, message text, thinking text, model name, tool name with truncated arguments, attachment filename, extension, and byte size. Grain: chats by `chat_id`; messages by `(chat_id, message_id)`. `role = user` is you; `role = assistant` is the model. Local timestamps use `Europe/Paris`.

**Dropped.** The `users` row (email), all of `settings` (including device id), `browser_state`, and attachment bytes. No email or IP columns on `ollama.*`. Warehouse text masks common API keys; the JSONL snapshot keeps the original message text. Model blobs and `~/.ollama/id_ed25519` are never opened.

**Explorer.** Ollama tab — scoreboard, streaks, model stack and rank bump, thinking, circadian + calendar, chat list + click-lock transcript, scatter, reply latency, tools, attachment metadata, forgotten/comebacks, word clouds. Compare / Correlations: messages + chats.
