# Spotify

Index: [Getting your data](../getting-your-data.md).

Two dumps, one explorer tab. Extended streaming history fills `spotify.plays`. Account data is additive and never replaces it.

| | Extended streaming history | Account data |
|--|----------------------------|--------------|
| Slug | `spotify` | `spotify_account` |
| Timezone | `Europe/Rome` | `Europe/Rome` |
| Explorer | Spotify tab | Library & playlists on the Spotify tab |

## Extended streaming history

**Request.** [Account Privacy](https://www.spotify.com/account/privacy/) → Download your data → **Extended streaming history**. It is a separate package from Account data and the Technical log; you can request them separately or together. Confirm the email Spotify sends. The UI often cites up to 30 days; many people get the zip in a few days. What each package contains is in [Understanding your data](https://support.spotify.com/us/article/understanding-your-data/). The zip contains a folder named `Spotify Extended Streaming History` with `Streaming_History_Audio_*.json`, optionally `Streaming_History_Video_*.json`, and a Read Me First PDF. An already-extracted folder with those JSON files also works. Account-package streaming history covers about the past year and does not fill `spotify.plays`.

```bash
uv run ingest /path/to/my_spotify_data.zip
```

**Kept.** Track, artist, episode, and audiobook names; play timestamps; platform; country; skip flags.

**Dropped.** IP addresses.

**Explorer.** Spotify tab (longitudinal charts, Wrapped-style scoreboard). Genre and decade charts appear after [MusicBrainz enrichment](../getting-your-data.md#optional-enrichment).

## Account data

**Request.** The same [Account Privacy](https://www.spotify.com/account/privacy/) page, **Account data** package, not Extended streaming history. Expect JSON such as `YourLibrary.json`, playlist files, `SearchQueries.json`, `Userdata.json`, and about one year of `StreamingHistory_*`. The folder inside the zip is `Spotify Account Data`.

This ingest does **not** replace `spotify.plays`.

```bash
uv run ingest /path/to/my_spotify_account_data.zip
```

**Kept.** Library items, playlists and their tracks, search queries, and a roughly one-year name-only play slice (`spotify.account_plays`).

**Dropped.** Identity, addresses, payments, and ad identifiers.

**Explorer.** Library & playlists section on the Spotify tab, once those tables exist.
