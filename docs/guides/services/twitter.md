# Twitter / X

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `twitter` | `Europe/Rome` | Twitter tab |

## Request

Settings and privacy → Your account → Download an archive of your data → verify → Request archive ([how to download your X archive](https://help.x.com/en/managing-your-account/how-to-download-your-x-archive)). Wait for the email or in-app notice (often about a day; it can be longer), then download the zip from the same settings page.

This loader targets the classic layout still reported in 2026: `data/*.js` files whose first line looks like `window.YTD.<name>.partN = [` (at least `tweets.js`) plus `Your archive.html`. A zip or the extracted archive folder both work. If the archive is not that YTD-wrapped JS, ingest fails clearly instead of guessing. Bookmarks are often absent.

## Ingest

```bash
uv run ingest /path/to/twitter-archive
```

**Kept.** Tweets, likes, followers and following, DM text.

**Dropped.** IPs, emails, phones, ads, and device tokens. Media stays in the archive; the warehouse stores kinds and paths only.

**Explorer.** Twitter tab.
