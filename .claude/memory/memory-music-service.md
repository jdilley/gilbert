# Music Service

## Summary
Music browse / search / play service backed entirely by the user's Sonos
system. Lists favorites and Sonos playlists zero-config, searches via
SoCo SMAPI against whichever music service is linked on Sonos (typically
Spotify), and plays resolved URIs through the speaker service.

## Details

### Interface
- `src/gilbert/interfaces/music.py` — `MusicBackend` ABC plus unified
  `MusicItem` dataclass (`id`, `title`, `kind`, `subtitle`, `uri`,
  `didl_meta`, `album_art_url`, `duration_seconds`, `service`).
- `MusicItemKind` enum: `TRACK`, `ALBUM`, `ARTIST`, `PLAYLIST`, `STATION`,
  `FAVORITE`.
- `Playable` dataclass: `uri`, `didl_meta`, `title`. Produced by
  `resolve_playable()` and handed to the speaker backend.
- Backend methods: `list_favorites`, `list_playlists`, `search(query, *,
  kind, limit)`, `resolve_playable(item)`.
- `MusicSearchUnavailableError` — raised by `search()` when the backend
  can't authenticate its linked service yet. Services should catch this
  and show a legible message.
- **No ID-based lookups.** There is no `get_track(id)` / `get_album(id)`
  because Sonos can't retrieve arbitrary items by ID across linked
  services — that was a Spotify-Web-API-shaped assumption.

### Sonos Backend
- `src/gilbert/integrations/sonos_music.py` — `SonosMusic`, the only
  registered backend.
- **Favorites** via `device.music_library.get_sonos_favorites()` →
  `MusicItem` (with URI for tracks, DIDL meta for stations/containers).
- **Playlists** via `device.get_sonos_playlists()` → `MusicItem` with
  direct `file:///...savedqueues.rsq#N` URIs.
- **Search** via `soco.music_services.MusicService(preferred_service,
  token_store=..., device=...).search(kind, query, count=limit)`. Needs
  a one-time SMAPI auth token (per-linked-service, not per-user).
  Results carry an opaque `item_id` — `resolve_playable()` then calls
  `sonos_uri_from_id()` to get a playable URI.
- **Token persistence** via an in-memory `_InMemoryTokenStore`
  (`TokenStoreBase` subclass) seeded from config on init and re-read
  after `complete_authentication`. Admin triggers the flow from the
  settings UI; the token ends up in `music.settings.auth_token` /
  `auth_key` (both sensitive `ConfigParam`s).
- Self-discovers devices via `soco.discover()` — doesn't share a handle
  with `SonosSpeaker` (that would violate the no-cross-integration rule).

### Service
- `src/gilbert/core/services/music.py` — `MusicService` implementing
  `Service`, `Configurable`, `ConfigActionProvider`, `ToolProvider`.
- Capabilities: `music`, `ai_tools`. Optional: `configuration`,
  `speaker_control`.
- `play_item(item, speaker_names, volume)` is the standard playback
  path: `backend.resolve_playable(item)` → `speaker_svc.play_on_speakers`
  with the resulting URI and DIDL meta.
- `now_playing(speaker_name=None)` delegates to the speaker service,
  which owns the authoritative "what's playing" state.
- Forwards backend actions (`link_spotify`, `test_connection`) via
  `_backend_actions.merge_backend_actions` /
  `_backend_actions.invoke_backend_action` helpers.

### AI Tools Exposed (grouped under `/music`)
- `list_favorites` (`/music favorites`) — list Sonos favorites
- `list_playlists` (`/music playlists`) — list saved Sonos playlists
- `search_music` (`/music search <query> [kind=tracks]`) — search the
  linked service; `kind` supports tracks/albums/playlists/artists/stations
- `play_music` (`/music play <title> [speakers=...] [source=...]`) —
  play by fuzzy title match. Default source order: favorites → playlists
  → search. `source` restricts lookup to one path.
- `now_playing` (`/music now [speaker]`) — speaker-sourced playback state

### Settings Actions
- `link_spotify` — two-phase flow: button 1 calls `begin_authentication`
  and opens the link URL; button 2 ("Continue") calls
  `complete_authentication` and persists the token pair via
  `ConfigActionResult.data['persist']` (settings.auth_token /
  settings.auth_key). Admin-only.
- `test_connection` — re-runs Sonos discovery; if an auth token exists,
  also runs a trivial SMAPI search to verify the token still works.

### Configuration
```yaml
music:
  enabled: false
  backend: sonos
  settings:
    preferred_service: Spotify   # any service linked on your Sonos
    auth_token: ""               # filled by the link flow; sensitive
    auth_key: ""                 # filled by the link flow; sensitive
```

## Related
- [Speaker System](memory-speaker-system.md) — playback target; plays
  `Playable.uri` with optional `didl_meta` envelope.
- [Radio DJ Service](memory-radio-dj-service.md) — consumes `search()`
  with `kind=PLAYLIST` to discover genre playlists.
- [Config Actions](memory-config-actions.md) — the action-button
  infrastructure this service helped drive.
- `tests/unit/test_music_service.py` — unit tests (30).
