# Sleep as Android

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `sleep` | `Europe/Rome` | Sleep tab |

## Request

In the app, not a web privacy portal. Left menu → Backup → Export data ([backup docs](https://sleep.urbandroid.org/docs/services/backup_data.html), [CSV schema](https://sleep.urbandroid.org/docs/devs/csv.html)). When it says Backup Successful, share the file off the device. The package is `sleep-export.zip` containing `sleep-export.csv` plus optional `prefs.xml`, `noise.json`, and `alarms.json`. A bare `sleep-export.csv` or a folder that contains it also works. Optional cloud copy: SleepCloud → Settings → Services → Cloud backup. Audio under `sleep-data/rec` is not in the zip.

Import the zip before the next sleep is recorded. If the app has already renamed it to `sleep-export.backup.zip`, rename that file back before importing.

## Ingest

```bash
uv run ingest /path/to/sleep-export.zip
```

**Kept.** Sessions, stage events, actigraphy samples, and alarms when `alarms.json` is present.

**Explorer.** Sleep tab. Re-export into the same zip layout for later ingests.
