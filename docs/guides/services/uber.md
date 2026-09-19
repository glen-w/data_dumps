# Uber

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `uber` | `Europe/Rome` | Uber tab |

## Request

[Privacy Center](https://myprivacy.uber.com/exploreyourdata) → **Download Your Data**. Explore Your Data on the same site is only a summary. In the app: Account → Settings → Privacy. Help: [request a copy of your personal data](https://help.uber.com/en/riders/article/request-a-copy-of-your-personal-data?nodeId=2c86900d-8408-4bac-b92a-956d793acd11). Sign in, complete two-step verification, and request the download. What you get depends on Rider, Eats, and Driver use. Uber cites up to 30 days. Download while you are still logged in.

The loader looks for `Rider/rider_lifetime_trips-0.csv` (official logical name: Trips Data Summary). An extracted `Uber Data/` folder works too. Names such as `trips_data.csv` show up in some write-ups; they are not what detect requires. Trip files can include latitude, longitude, and addresses. Those columns are dropped.

## Ingest

```bash
uv run ingest "/path/to/Uber Data Request.zip"
```

**Kept.** Rider trips (synthetic `trip_id`), Eats line items (`order_key` groups an order), ratings received, support ticket messages.

**Dropped.** Profile (name, email, phone, signup coordinates), payment methods, saved locations, rider and Eats app analytics (IPs, device ids, GPS), trip lat/lng, address strings, card numbers, and Eats special instructions. The same fields are scrubbed in `raw/uber/`.

**Explorer.** Uber tab. City maps use a static gazetteer because trip GPS is not stored.
