<p align="center">
  <img src="../../assets/logo.png" alt="" width="120">
</p>

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

Per-service request steps, detect shapes, and keep/drop lists live under [services/](services/). Add quirks there as they turn up; this table is the index. Request steps were checked against official help on 2026-09-19. Timings and zip names that help pages do not state are marked as such on the service page.

## Sources

| Service | Where to request | Point ingest at | Tab | Notes |
|---------|------------------|-----------------|-----|-------|
| [Spotify Extended](services/spotify.md#extended-streaming-history) | [Account Privacy](https://www.spotify.com/account/privacy/) → Extended streaming history | Zip or folder with `Streaming_History_Audio_*.json` | Spotify | Separate package from account data; UI cites up to 30 days |
| [Spotify Account](services/spotify.md#account-data) | Same page, Account data package | `Spotify Account Data/` folder | Spotify (library) | About one year of streams; does not replace `spotify.plays` |
| [Telegram](services/telegram.md) | Desktop → Settings → Advanced → Export Telegram data (JSON) | Folder or zip with `result.json` | Telegram | Not the EDPO DSAR form; media stays on disk |
| [LinkedIn](services/linkedin.md) | Settings & Privacy → Data privacy → larger data archive | `Connections.csv` + `Positions.csv` | LinkedIn | Desktop; a single fast category is not enough |
| [Twitter / X](services/twitter.md) | Settings → Your account → Download an archive | Classic `data/*.js` (`tweets.js`) | Twitter | Newer X layouts fail clearly |
| [Slack](services/slack.md) | Workspace admin → Import & export data → Export | Zip with `users.json`, `channels.json`, daily JSON | Slack | Public channels on all plans; private/DMs need Business+ |
| [Sleep as Android](services/sleep.md) | Left menu → Backup → Export data | `sleep-export.zip` or `sleep-export.csv` | Sleep | Audio recordings are not in the zip |
| [Mi Band](services/miband.md) | One-off CSV (not an app export) | `heart_rate.csv` (`dateTime,rate,rateZone`) | Mi Band | Frozen; do not extend |
| [Ring](services/ring.md) | Control Centre → Manage Your Data | `DeviceEvents.csv` + `RingDeviceRegistry/Device.csv` | Ring | Not Amazon Privacy Central |
| [Thunderbird](services/thunderbird.md) | Local profile (not a download) | Profile folder with `global-messages-db.sqlite` | Thunderbird | Help → Troubleshooting Information → Open Folder |
| [Browser](services/browser.md) | Firefox **Sky History Export** | Folder of history JSON | Browser | Not Mozilla’s account download; `places.sqlite` not yet |
| [Amazon](services/amazon.md) | [Privacy Central](https://www.amazon.co.uk/hz/privacy-central/data-requests/preview.html) (UK) | Folder of `All Data Categories*.zip` | Amazon | Click the validation email; multipart |
| [Duolingo](services/duolingo.md) | Website Settings → Export my data | Zip with `languages.csv`, `leaderboards.csv`, `profile.csv` | Duolingo | Prefer web; lesson history may be incomplete |
| [Uber](services/uber.md) | [Privacy Center](https://myprivacy.uber.com/exploreyourdata) → Download Your Data | Zip with `Rider/rider_lifetime_trips-0.csv` | Uber | Two-step verification; up to 30 days |
| [Google](services/google.md) | [Google Takeout](https://takeout.google.com) | Folder of `takeout-*.zip` or extracted `Takeout/` | Google | Calendar, Play, Maps saves, My Activity HTML, Tasks; download every part |
| [Airbnb](services/airbnb.md) | Account → Privacy → Request your personal data (HTML) | `Airbnb_data_request_*.zip` | Airbnb | Zip name is not on the help page |
| [ChatGPT](services/chatgpt.md) | Settings → Data controls → Export data | Zip with `conversations-NNN.json` | ChatGPT | Download within 24 hours; not the API platform |

## Tools

**Tools** (wrench icon, next to Home) is not a dump. It lists every email address the exports contain: account fields the source tabs skip, other people's profiles and contacts, and addresses that only show up inside chats, tweets, reviews, or mail. Each row is one place that address appeared, so you can see why it is there. Under that, it lists login, session, device, and access-log IP addresses from the files those loaders skip, and plots city centroids when the GeoLite2 databases are installed.

Source tables still have no email or IP columns. Mail message text is not stored; if a Thunderbird profile is on this machine, Tools reads bodies only to pull addresses out. The lists are cached at `$DATA_DUMPS_ROOT/warehouse/email_inventory.json` and `ip_inventory.json` (outside git) and rebuilt when those files change. For locations and ISPs, download GeoLite2 City and ASN (free MaxMind account) and place the files at `$DATA_DUMPS_ROOT/warehouse/geoip/GeoLite2-City.mmdb` and `GeoLite2-ASN.mmdb`. Counts only, from a stopped dashboard:

```bash
uv run email-inventory
uv run ip-inventory
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
