# Sleep as Android

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `sleep` | `Europe/Rome` | Sleep tab |

## Request

In the app, export or back up sleep data. The canonical package is `sleep-export.zip` containing `sleep-export.csv` plus optional `prefs.xml`, `noise.json`, and `alarms.json`. A bare `sleep-export.csv` or a folder that contains it also works.

## Ingest

```bash
uv run ingest /path/to/sleep-export.zip
```

**Kept.** Sessions, stage events, actigraphy samples, and alarms when `alarms.json` is present.

**Explorer.** Sleep tab. Re-export into the same zip layout for later ingests.
