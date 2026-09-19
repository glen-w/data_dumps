# Getting your data

Request an export from the service, put the zip or folder anywhere you like, then ingest it. The default data root is `~/Documents/data_dumps_raw` (`DATA_DUMPS_ROOT`). Nothing in that tree belongs in git.

Stop the dashboard before every ingest. `catalog.duckdb` allows one process at a time. See [WAREHOUSE.md](../WAREHOUSE.md).

```bash
# dashboard must not be running
uv run ingest /path/to/export
uv run marimo run notebooks/explorer.py --host 127.0.0.1 --port 2718
```

`ingest` picks a loader by file shape. If nothing matches, it exits with `no loader matched this path`.

Wall-clock columns use a hardcoded zone, not the machine timezone: `Europe/Rome` for most sources, `Europe/Paris` for Slack, Google, Airbnb, and ChatGPT, `Europe/London` for Ring.

Per-service request steps, detect shapes, and keep/drop lists live under [services/](services/). Add quirks there as they turn up; this table is the index.

## Sources

| Service | Where to request | Point ingest at | Tab | Notes |
|---------|------------------|-----------------|-----|-------|
| [Spotify Extended](services/spotify.md#extended-streaming-history) | Account → Privacy → Download your data | Zip or folder with `Streaming_History_Audio_*.json` | Spotify | Separate request from account data; can take weeks |
| [Spotify Account](services/spotify.md#account-data) | Same Privacy page, ordinary download | `Spotify Account Data/` folder | Spotify (library) | Does not replace `spotify.plays` |
| [Telegram](services/telegram.md) | Desktop → Settings → Advanced → Export Telegram data | Folder or zip with `result.json` | Telegram | Media stays on disk |
| [LinkedIn](services/linkedin.md) | Settings & Privacy → Data privacy → Get a copy | Complete archive (`Connections.csv` + `Positions.csv`) | LinkedIn | Basic archive is not enough |
| [Twitter / X](services/twitter.md) | Settings → Your account → Download an archive | Classic `data/*.js` (`tweets.js`) | Twitter | Newer X layouts fail clearly |
| [Slack](services/slack.md) | Workspace admin → Import/Export Data → Export | Zip with `users.json`, `channels.json`, daily JSON | Slack | Admin export only |
| [Sleep as Android](services/sleep.md) | In-app export or backup | `sleep-export.zip` or `sleep-export.csv` | Sleep | |
| [Mi Band](services/miband.md) | One-off CSV (not an app export) | `heart_rate.csv` (`dateTime,rate,rateZone`) | Mi Band | Frozen; do not extend |
| [Ring](services/ring.md) | Account privacy → download my data | `All Data Categories.zip` (`DeviceEvents.csv` + registry) | Ring | |
| [Thunderbird](services/thunderbird.md) | Local profile (not a download) | Profile folder with `global-messages-db.sqlite` | Thunderbird | Pass `--identity` or `DATA_DUMPS_TB_IDENTITIES` |
| [Browser](services/browser.md) | Firefox **Sky History Export** | Folder of history JSON | Browser | Visit-level `places.sqlite` not yet |
| [Amazon](services/amazon.md) | Account → Request Your Data | Folder of `All Data Categories*.zip` | Amazon | Multipart; a single zip also works |
| [Duolingo](services/duolingo.md) | Privacy → download your data | Zip with `languages.csv`, `leaderboards.csv`, `profile.csv` | Duolingo | |
| [Uber](services/uber.md) | Account → Privacy → Request your data | Zip with `Rider/rider_lifetime_trips-0.csv` | Uber | |
| [Google](services/google.md) | [Google Takeout](https://takeout.google.com) | Folder of `takeout-*.zip` or extracted `Takeout/` | Google | Multipart |
| [Airbnb](services/airbnb.md) | Account → Privacy → Request your personal data | `Airbnb_data_request_*.zip` | Airbnb | |
| [ChatGPT](services/chatgpt.md) | Settings → Data controls → Export data | Zip with `conversations-NNN.json` | ChatGPT | |

## Tools

**Tools** (wrench icon, next to Home) is not a dump. It lists every email address the exports contain: account fields the source tabs skip, other people's profiles and contacts, and addresses that only show up inside chats, tweets, reviews, or mail. Each row is one place that address appeared, so you can see why it is there.

Source tables still have no email columns. Mail message text is not stored; if a Thunderbird profile is on this machine, Tools reads bodies only to pull addresses out. The list is cached at `$DATA_DUMPS_ROOT/warehouse/email_inventory.json` (outside git) and rebuilt when those files change. Counts only, from a stopped dashboard:

```bash
uv run email-inventory
```

## Optional enrichment

Stop the dashboard first ([WAREHOUSE.md](../WAREHOUSE.md)).

MusicBrainz genre and decade tags for the Spotify library. Limits default to `0` (no cap): every artist and track above the minimum hours, about one request per second.

```bash
uv run enrich-musicbrainz --dry-run
uv run enrich-musicbrainz
```

Optional local narratives. The prompt is aggregates only, never raw rows. Default endpoint is loopback Ollama.

```bash
export DATA_DUMPS_LLM_ENABLED=1
export DATA_DUMPS_LLM_MODEL=qwen2.5:7b
```

Remote LiteLLM is opt-in: `uv sync --extra llm`, then `DATA_DUMPS_LLM_PROVIDER=litellm`.
