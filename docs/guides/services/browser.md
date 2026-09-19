# Browser history

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `browser` | `Europe/Rome` | Browser tab |

## Request

Use the Firefox add-on [History Export (Skyweb)](https://addons.mozilla.org/en-US/firefox/addon/sky-history-export/) from AMO. Install it, open Options, and export history as JSON (the file is often named `data.json`). Objects have `url`, `title`, `lastVisitTime`, and `visitCount`. A one-time Chrome-style `history.json` in the same folder is merged; Chrome’s local history is about 90 days. Grain is one row per URL (last visit and visit count), not individual visits.

Do not use Mozilla’s account “download your data” export, and do not point ingest at `places.sqlite`.

## Ingest

```bash
uv run ingest /path/to/firefox/
```

**Dropped.** Sensitive query parameters (`secret`, `token`, and similar). LAN and localhost URLs are flagged private.

**Not yet.** Visit-level Firefox `places.sqlite` (needed for circadian and session charts).

**Explorer.** Browser tab.
