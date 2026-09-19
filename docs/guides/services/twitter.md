# Twitter / X

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `twitter` | `Europe/Rome` | Twitter tab |

## Request

Settings → Your account → Download an archive of your data. This loader targets the classic HTML-viewer layout: `data/*.js` files that assign `window.YTD.*.part0` (at least `tweets.js`). A zip or the extracted archive folder both work.

Newer X dumps can use a different layout. v1 fails clearly instead of guessing.

## Ingest

```bash
uv run ingest /path/to/twitter-archive
```

**Kept.** Tweets, likes, followers and following, DM text.

**Dropped.** IPs, emails, phones, ads, and device tokens. Media stays in the archive; the warehouse stores kinds and paths only.

**Explorer.** Twitter tab.
