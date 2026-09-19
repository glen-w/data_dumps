# Browser history

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `browser` | `Europe/Rome` | Browser tab |

## Request

Export history as JSON with the Firefox **Sky History Export** extension (objects with `url`, `title`, `lastVisitTime`, `visitCount`). A one-time Chrome-style `history.json` in the same folder is merged. Grain is one row per URL (last visit and visit count), not individual visits.

## Ingest

```bash
uv run ingest /path/to/firefox/
```

**Dropped.** Sensitive query parameters (`secret`, `token`, and similar). LAN and localhost URLs are flagged private.

**Not yet.** Visit-level Firefox `places.sqlite` (needed for circadian and session charts).

**Explorer.** Browser tab.
