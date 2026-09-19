# Slack

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `slack` | `Europe/Paris` | Slack tab |

## Request

This is a **workspace admin** export, not something every member can download. Desktop → Admin → Workspace settings → Security → [Import & export data → Export](https://slack.com/help/articles/201658943-Export-your-workspace-data) → Start Export. How the zip is laid out: [How to read Slack data exports](https://slack.com/help/articles/220556107-How-to-read-Slack-data-exports).

Public channels: Owners and Admins on every plan. Private channels and DMs: Business+ or Enterprise, and they need approval. Free and Pro include those only in limited legal or consent cases.

A member in the UK or EU who is not an admin cannot self-serve message and file “Customer Data”. Ask the workspace Primary Owner (Slack is the processor). For account and usage data Slack holds itself (“Other Information”), email privacy@slack.com. See [Slack data management](https://slack.com/trust/data-management).

The export is a zip (or an extracted folder) with `users.json`, `channels.json`, and one folder per channel of daily `YYYY-MM-DD.json` files. File-conversation folders named `FC:<id>:<title>` become channels of kind `file_conversation`.

## Ingest

```bash
uv run ingest /path/to/slack-export.zip
```

Daily files are streamed from the zip. Only `users.json` and `channels.json` are copied to `raw/slack/`. Canvases, lists, integration logs, and huddle transcripts are skipped.

**Kept.** Display names and message text. `<@U…>` mentions resolve to `@Name`.

**Dropped.** Emails, phones, Skype handles, and avatar URLs.

**Explorer.** Slack tab, including a person spotlight. Bots and system subtypes (joins, renames) are loaded and hidden by default.
