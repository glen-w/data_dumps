# Mi Band heart rate

Index: [Getting your data](../getting-your-data.md).

Frozen one-off. There is no multi-format wearable pipeline, and this loader should not be extended.

| Slug | Timezone | Explorer |
|------|----------|----------|
| `miband` | `Europe/Rome` | Mi Band tab |

## Detect

A CSV named `heart_rate.csv` (or any CSV) with columns `dateTime,rate,rateZone`.

## Ingest

```bash
uv run ingest /path/to/heart_rate.csv
```

**Explorer.** Mi Band tab. Useful as a heart-rate overlay for Sleep; do not add other Mi Band metrics.
