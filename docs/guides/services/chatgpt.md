# ChatGPT

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `chatgpt` | `Europe/Paris` | ChatGPT tab |

## Request

ChatGPT → Settings → Data controls → Export data. The zip contains `conversations-NNN.json` shards, plus shared-link and library metadata.

## Ingest

```bash
uv run ingest /path/to/chatgpt.zip
```

**Kept.** Conversation titles, message text, model slugs, thinking and multimodal content types, shared links, library file metadata. Message grain is `(conversation_id, message_id)`.

**Dropped.** Email and phone from `user.json`, `ads.json`. `.dat` media and `chat.html` are not copied into `raw/chatgpt/`.

**Explorer.** ChatGPT tab. Local timestamps use `Europe/Paris`.
