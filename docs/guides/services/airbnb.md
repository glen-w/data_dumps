# Airbnb

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `airbnb` | `Europe/Paris` | Airbnb tab |

## Request

Airbnb account → Privacy → Request your personal data. The HTML export zip is usually named like `Airbnb_data_request_*.zip`.

## Ingest

```bash
uv run ingest /path/to/airbnb.zip
```

**Kept.** Account id (guest versus host is derived from it), reservations (grain: confirmation code), searches (city, country, and search-pin lat/lon), reviews, wishlists.

**Dropped.** Profile email, name, phone, IPs, birth date, street addresses, activity log, payments and KYC, messages, search telemetry, reservation `Message`, and search `Raw Location`. Profile HTML is not copied into `raw/airbnb/`.

**Explorer.** Airbnb tab. Local timestamps use `Europe/Paris`.
