# Thunderbird

Index: [Getting your data](../getting-your-data.md).

This is not a download. Point ingest at a Thunderbird profile folder that contains `global-messages-db.sqlite` (on macOS, often `~/Library/Thunderbird/Profiles/<id>.default-release`). The loader snapshots that index read-only. It does not copy or move mail directories.

| Slug | Timezone | Explorer |
|------|----------|----------|
| `thunderbird` | `Europe/Rome` | Thunderbird tab |

## Identities

Own addresses mark sent versus received. They are read from `prefs.js`, from repeatable `--identity`, or from `DATA_DUMPS_TB_IDENTITIES` (comma-separated).

## Ingest

```bash
uv run ingest /path/to/Thunderbird/Profiles/<id>.default-release \
  --identity you@example.com
```

**Kept.** Message metadata: subjects, addresses and domains, folders, flags, attachment names. Heuristic signals: newsletter, receipt, subscription, signup.

**Dropped.** Message bodies. Mail files stay where Thunderbird put them.

**Explorer.** Thunderbird tab.
