# Ring

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `ring` | `Europe/London` | Ring tab |

## Request

Ring account privacy / “download my data”. The zip is typically named `All Data Categories.zip` and must contain `DeviceEvents.csv` and `RingDeviceRegistry/Device.csv`. An extracted folder with those files also works.

## Ingest

```bash
uv run ingest "/path/to/All Data Categories.zip"
```

**Kept.** Device names, city and country, online/offline events, sparse motion, app events, subscriptions, accounting totals.

**Dropped.** Address, coordinates, SSID, IPs, hardware ids, and email bodies.

**Explorer.** Ring tab.
