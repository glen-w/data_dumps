# ChatGPT

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `chatgpt` | `Europe/Paris` | ChatGPT tab |

## Request

On chatgpt.com (chat.openai.com redirects there): Settings → Data controls → Export data ([export help](https://help.openai.com/en/articles/7260999-export-your-data-from-chatgpt)). Fallback: [privacy.openai.com](https://privacy.openai.com/) → consumer ChatGPT → Download my data. This is not platform.openai.com (the API). Confirm the export, wait up to seven days for the email or SMS, then download within **24 hours** while signed in.

OpenAI may ship one `conversations.json` or numbered `conversations-NNN.json` shards, plus shared-link and library metadata. This loader matches the numbered shards, together with `user.json`, `export_manifest.json`, or `chat.html`. A zip that only contains `conversations.json` does not detect yet.

## Ingest

```bash
uv run ingest /path/to/chatgpt.zip
```

**Kept.** Conversation titles, message text, model slugs, thinking and multimodal content types, shared links, library file metadata. Message grain is `(conversation_id, message_id)`.

**Dropped.** Email and phone from `user.json`, `ads.json`. `.dat` media and `chat.html` are not copied into `raw/chatgpt/`.

**Explorer.** ChatGPT tab. Local timestamps use `Europe/Paris`.
