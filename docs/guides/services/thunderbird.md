# Thunderbird

Index: [Getting your data](../getting-your-data.md).

This is not a download. In Thunderbird: Help → Troubleshooting Information → Profile Folder → Open Folder (Show in Finder / Open Directory). Point ingest at that folder. It must contain `global-messages-db.sqlite`. The loader snapshots that index read-only. It does not copy or move mail directories.

Fallbacks if Open Folder is unavailable: macOS `~/Library/Thunderbird/Profiles/`, Windows `%APPDATA%\Thunderbird\Profiles\`, Linux `~/.thunderbird/`. Prefer the button over guessing the path.

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
