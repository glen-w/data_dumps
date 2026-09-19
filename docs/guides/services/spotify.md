# Spotify

Index: [Getting your data](../getting-your-data.md).

Two dumps, one explorer tab. Extended streaming history fills `spotify.plays`. Account data is additive and never replaces it.

| | Extended streaming history | Account data |
|--|----------------------------|--------------|
| Slug | `spotify` | `spotify_account` |
| Timezone | `Europe/Rome` | `Europe/Rome` |
| Explorer | Spotify tab | Library & playlists on the Spotify tab |

## Extended streaming history

**Request.** Spotify account → Privacy → Download your data. Ask for **Extended streaming history**. It is a separate request from account data and can take weeks. The zip contains a folder named `Spotify Extended Streaming History` with `Streaming_History_Audio_*.json` and optionally `Streaming_History_Video_*.json`. An already-extracted folder with those files also works.

```bash
uv run ingest /path/to/my_spotify_data.zip
```

**Kept.** Track, artist, episode, and audiobook names; play timestamps; platform; country; skip flags.

**Dropped.** IP addresses.

**Explorer.** Spotify tab (longitudinal charts, Wrapped-style scoreboard). Genre and decade charts appear after [MusicBrainz enrichment](../getting-your-data.md#optional-enrichment).

## Account data

**Request.** The ordinary “Download your data” zip, not Extended streaming history. It contains a `Spotify Account Data` folder (`YourLibrary.json`, playlist JSON, `SearchQueries.json`).

This ingest does **not** replace `spotify.plays`.

```bash
uv run ingest /path/to/my_spotify_account_data.zip
```

**Kept.** Library items, playlists and their tracks, search queries, and a roughly one-year name-only play slice (`spotify.account_plays`).

**Dropped.** Identity, addresses, payments, and ad identifiers.

**Explorer.** Library & playlists section on the Spotify tab, once those tables exist.
