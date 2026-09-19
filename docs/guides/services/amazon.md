# Amazon

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `amazon` | `Europe/Rome` | Amazon tab |

## Request

Amazon account → Request Your Data. The bundle is usually several `All Data Categories*.zip` files plus `FileDescriptions.csv`. Point ingest at the **folder**. A single curated zip, or an extracted `Your Amazon Orders/` tree, also works.

## Ingest

```bash
uv run ingest /path/to/amazon
```

**Kept.** Order items, orders, searches, returns, Audible / Video / Music / Kindle metadata, Rufus, and structured Alexa use. `amazon.dump_inventory` records the on-disk footprint.

**Dropped.** Voice `.wav` files (inventory only), invoice PDFs, cards, addresses, IPs, and geolocation. Spend stays multi-currency; amounts are not converted.

**Explorer.** Amazon tab. A thinner standalone notebook is `notebooks/amazon.py`.
