# Telegram

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `telegram` | `Europe/Rome` | Telegram tab |

## Request

Telegram Desktop → Settings → Advanced → Export Telegram data. You get a folder (or a zip of that folder) whose `result.json` is the export. Media files can stay beside it; they are not copied into the warehouse.

## Ingest

```bash
uv run ingest /path/to/Telegram_Export
```

**Kept.** Chats, message text, reactions, contact display info. Message IDs are unique per chat: grain is `(chat_id, message_id)`.

**Dropped.** Session IPs. Media bytes stay on disk; the warehouse stores relative paths only. Saved-message file contents stay on disk as files.

**Explorer.** Telegram tab (scoreboard, me vs them, calendar, reply scatter, forgotten chats).
