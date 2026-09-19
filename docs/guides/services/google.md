# Google Takeout

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `google` | `Europe/Paris` | Google tab |

## Request

[Google Takeout](https://takeout.google.com) ([how Takeout works](https://support.google.com/accounts/answer/3024190)). Deselect all, then turn on only:

- Google Calendar
- Google Play (narrow the sub-products if Takeout offers that)
- Saved (Maps saves)
- Google Photos, only if you want sidecar metadata — the media itself is large and is not loaded
- My Activity, format **HTML**
- Google Tasks

Leave off Gmail, Google Contacts, Google Pay, and Timeline (GPS). On the next step choose Zip, the largest archive size you can (50 GB means fewer parts), delivery by email link or Drive, then Create export. Download every `takeout-*.zip` within about seven days (five downloads per link). A missing part means an incomplete export.

Point ingest at the folder of those zips, or at an extracted `Takeout/` tree. `Takeout/Calendar` or `Takeout/My Activity` is enough to detect.

## Ingest

```bash
uv run ingest /path/to/google
```

**Kept.** Calendar events (grain `(calendar_name, uid)`; habit placeholders dated 1970 are skipped), Play Store library and purchases, Maps saved places (name and country only), saved lists without street addresses, photo sidecar metadata, My Activity HTML, tasks. Photos and Drive bytes stay in the zips and are inventoried only.

**Dropped.** Access logs (IPs and Gaia ids), mail mbox bodies, contacts, profile and account HTML, Pay and Wallet, street addresses, photo and Maps GPS, payment emails on Play purchases.

**Explorer.** Google tab. Local timestamps use `Europe/Paris`.
