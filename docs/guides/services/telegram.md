# Telegram

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `telegram` | `Europe/Rome` | Telegram tab |

## Request

Telegram Desktop → Settings → Advanced → Export Telegram data. Choose **JSON**. That writes `result.json` plus optional media folders ([export schema](https://core.telegram.org/import-export)). HTML (`export_results.html`) is for browsing in a browser and is not what this loader reads. Media is optional; a large media export can take hours and a lot of disk. Files can stay beside `result.json`; they are not copied into the warehouse.

This is not an EEA DSAR filed through [EDPO](https://edpo.com/telegram-gdpr-data-request/). That form is a legal request, not the Desktop export.

## Ingest

```bash
uv run ingest /path/to/Telegram_Export
```

**Kept.** Chats, message text, reactions, contact display info. Message IDs are unique per chat: grain is `(chat_id, message_id)`.

**Dropped.** Session IPs. Media bytes stay on disk; the warehouse stores relative paths only. Saved-message file contents stay on disk as files.

**Explorer.** Telegram tab (scoreboard, me vs them, calendar, reply scatter, forgotten chats).
