# LinkedIn

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `linkedin` | `Europe/Rome` | LinkedIn tab |

## Request

Desktop only: Me → Settings & Privacy → Data privacy → [Download your data](https://www.linkedin.com/help/linkedin/answer/a1339364) / Get a copy of your data. Select **Download larger data archive**, not one fast category, if you need Connections and Positions ([connections help](https://www.linkedin.com/help/linkedin/answer/a566336)). A single category is often emailed within minutes (some take up to 48 hours). The larger archive is usually emailed within 24 hours, and the link lasts 72 hours.

Detect requires both `Connections.csv` and `Positions.csv` (zip or extracted folder). `Connections.csv` often has a notes preamble before the header; the loader skips it. Names like `Basic_` versus `Complete_LinkedInDataExport_*.zip` are what people report, not official labels. Connection emails appear only when the other person allows it; this loader drops them anyway.

## Ingest

```bash
uv run ingest /path/to/Complete_LinkedInDataExport.zip
```

**Kept.** Connections (without email), messages, positions, education, reactions, shares, comments.

**Dropped.** IPs, emails, phones, ads, inferences, receipts, and identity documents. Those files are not copied into `raw/linkedin/`.

**Explorer.** LinkedIn tab (network over time, career and location map, messages, feed activity).
