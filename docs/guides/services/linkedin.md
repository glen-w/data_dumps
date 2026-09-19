# LinkedIn

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `linkedin` | `Europe/Rome` | LinkedIn tab |

## Request

Settings & Privacy → Data privacy → Get a copy of your data. Choose the **Complete** archive. Basic is a subset and may lack files the loader expects. Detect requires both `Connections.csv` and `Positions.csv` (zip or extracted folder). `Connections.csv` has a notes preamble before the header; the loader skips it.

## Ingest

```bash
uv run ingest /path/to/Complete_LinkedInDataExport.zip
```

**Kept.** Connections (without email), messages, positions, education, reactions, shares, comments.

**Dropped.** IPs, emails, phones, ads, inferences, receipts, and identity documents. Those files are not copied into `raw/linkedin/`.

**Explorer.** LinkedIn tab (network over time, career and location map, messages, feed activity).
