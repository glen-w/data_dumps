# Google Takeout

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `google` | `Europe/Paris` | Google tab |

## Request

[Google Takeout](https://takeout.google.com). Download as multiple archives. Point ingest at the folder of `takeout-*.zip` files, or at an extracted `Takeout/` tree (`Takeout/Calendar` or `Takeout/My Activity` is enough to detect).

## Ingest

```bash
uv run ingest /path/to/google
```

**Kept.** Calendar events (grain `(calendar_name, uid)`; habit placeholders dated 1970 are skipped), Play Store library and purchases, Maps saved places (name and country only), saved lists without street addresses, photo sidecar metadata, My Activity HTML, tasks. Photos and Drive bytes stay in the zips and are inventoried only.

**Dropped.** Access logs (IPs and Gaia ids), mail mbox bodies, contacts, profile and account HTML, Pay and Wallet, street addresses, photo and Maps GPS, payment emails on Play purchases.

**Explorer.** Google tab. Local timestamps use `Europe/Paris`.
