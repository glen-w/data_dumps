# Uber

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `uber` | `Europe/Rome` | Uber tab |

## Request

Uber account → Privacy → Request your data (or privacy.uber.com). The zip contains `Rider/rider_lifetime_trips-0.csv`. An extracted `Uber Data/` folder works too.

## Ingest

```bash
uv run ingest "/path/to/Uber Data Request.zip"
```

**Kept.** Rider trips (synthetic `trip_id`), Eats line items (`order_key` groups an order), ratings received, support ticket messages.

**Dropped.** Profile (name, email, phone, signup coordinates), payment methods, saved locations, rider and Eats app analytics (IPs, device ids, GPS), trip lat/lng, address strings, card numbers, and Eats special instructions. The same fields are scrubbed in `raw/uber/`.

**Explorer.** Uber tab. City maps use a static gazetteer because trip GPS is not stored.
