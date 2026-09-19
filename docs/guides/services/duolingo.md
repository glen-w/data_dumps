# Duolingo

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `duolingo` | `Europe/Rome` | Duolingo tab |

## Request

Prefer the website over the app. Log in at duolingo.com → Settings → Export my data (Data Vault is the same request). Overview: [duolingo.com/privacy](https://www.duolingo.com/privacy). The page may say up to 30 days; people often get the email within hours.

The zip (or an extracted folder) must include `languages.csv`, `leaderboards.csv`, and `profile.csv`. Confirm those names on the file you receive; the vault is CSV-oriented and may omit full lesson history.

## Ingest

```bash
uv run ingest /path/to/duolingo.zip
```

**Kept.** Username and join time, languages, leaderboards, inventory without payment fields, friend counts, and progress events. The skill-tree blob is stored as a byte length only. Grain for progress is one row per `event_timestamp` and language pair.

**Dropped.** Auth, IPs, email and full name, blast/notify, avatars, experiments, tutor and video, DET profile, `payment_processor`, and `code_id`. Those fields are scrubbed in `raw/duolingo/` as well.

**Explorer.** Duolingo tab.
