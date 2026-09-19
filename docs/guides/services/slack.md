# Slack

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `slack` | `Europe/Paris` | Slack tab |

## Request

This is a **workspace admin** export, not something every member can download. In the workspace admin tools: Import/Export Data → Export. You get a zip (or an extracted folder) with `users.json`, `channels.json`, and one folder per channel of daily `YYYY-MM-DD.json` files. File-conversation folders named `FC:<id>:<title>` become channels of kind `file_conversation`.

## Ingest

```bash
uv run ingest /path/to/slack-export.zip
```

Daily files are streamed from the zip. Only `users.json` and `channels.json` are copied to `raw/slack/`. Canvases, lists, integration logs, and huddle transcripts are skipped.

**Kept.** Display names and message text. `<@U…>` mentions resolve to `@Name`.

**Dropped.** Emails, phones, Skype handles, and avatar URLs.

**Explorer.** Slack tab, including a person spotlight. Bots and system subtypes (joins, renames) are loaded and hidden by default.
