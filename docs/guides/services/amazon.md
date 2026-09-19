# Amazon

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `amazon` | `Europe/Rome` | Amazon tab |

## Request

Use the marketplace that holds the orders. UK: [Privacy Central](https://www.amazon.co.uk/hz/privacy-central/data-requests/preview.html) → request your data ([help](https://www.amazon.co.uk/gp/help/customer/display.html?nodeId=TP1zlemejtTn6pwYKS)). Select categories or all, submit, then click the **validation** link in the email. Without that click the request is abandoned. The download is often ready in days; about a month is reported as the long end.

The bundle is usually several `All Data Categories*.zip` files plus `FileDescriptions.csv`. Point ingest at the **folder**. A single curated zip, `Your Orders.zip`, or an extracted `Your Amazon Orders/` tree also works. Some regions ship JSON plus a schema file beside each export. Alexa audio is inventoried only when those files are present; do not assume WAVs. Ring is a separate Control Centre flow, not this request.

## Ingest

```bash
uv run ingest /path/to/amazon
```

**Kept.** Order items, orders, searches, returns, Audible / Video / Music / Kindle metadata, Rufus, and structured Alexa use. `amazon.dump_inventory` records the on-disk footprint.

**Dropped.** Voice `.wav` files (inventory only), invoice PDFs, cards, addresses, IPs, and geolocation. Spend stays multi-currency; amounts are not converted.

**Explorer.** Amazon tab. A thinner standalone notebook is `notebooks/amazon.py`.
