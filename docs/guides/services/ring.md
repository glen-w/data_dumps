# Ring

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `ring` | `Europe/London` | Ring tab |

## Request

UK: sign in on the app or ring.com → Control Centre → Manage Your Data → Download Your Personal Data or Download Device Data ([account and privacy](https://ring.com/gb/en/support/articles/t5i23/managing-your-ring-account-and-privacy-settings), [transfer to third parties](https://ring.com/gb/en/support/articles/8v5v5/transfer-ring-data-third-parties)). Confirm with your password, then use the emailed link. This is not Amazon Privacy Central. Deleting the data deletes the account.

The zip we have seen is named `All Data Categories.zip`. That filename is not confirmed on the help page. It must contain `DeviceEvents.csv` and `RingDeviceRegistry/Device.csv`. An extracted folder with those files also works. The Personal Data versus Device Data label varies.

## Ingest

```bash
uv run ingest "/path/to/All Data Categories.zip"
```

**Kept.** Device names, city and country, online/offline events, sparse motion, app events, subscriptions, accounting totals.

**Dropped.** Address, coordinates, SSID, IPs, hardware ids, and email bodies.

**Explorer.** Ring tab.
