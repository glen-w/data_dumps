# Airbnb

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `airbnb` | `Europe/Paris` | Airbnb tab |

## Request

Account → Privacy (or Privacy & sharing) → Request your personal data ([UK help](https://www.airbnb.co.uk/help/article/3255), [personal information](https://www.airbnb.co.uk/help/article/2273)). Choose **HTML**. Excel and JSON are offered too; this loader reads the HTML export. Complete identity verification if Airbnb asks. Help does not state how many days the file takes. A formal access request still sits under the usual one-month GDPR clock. Download before the link in the email expires.

The zip we detect is named like `Airbnb_data_request_*.zip`. That pattern is not quoted on Help 3255, so confirm it on the next live download. It extracts to a folder such as `Airbnb_data_file_DayMonthYear_GMT` with `readme.HTML`, `HTML/` category pages, and optional `attachments/` and `images/`. One request covers guest and host data; host-only folders are simply absent when you have none.

## Ingest

```bash
uv run ingest /path/to/airbnb.zip
```

**Kept.** Account id (guest versus host is derived from it), reservations (grain: confirmation code), searches (city, country, and search-pin lat/lon), reviews, wishlists.

**Dropped.** Profile email, name, phone, IPs, birth date, street addresses, activity log, payments and KYC, messages, search telemetry, reservation `Message`, and search `Raw Location`. Profile HTML is not copied into `raw/airbnb/`.

**Explorer.** Airbnb tab. Local timestamps use `Europe/Paris`.
