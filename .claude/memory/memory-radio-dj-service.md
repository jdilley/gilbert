# Radio DJ Service

## Summary
Context-aware music DJ that selects genres based on who's present, learns user preferences (likes/vetoes) over time, and rotates through default genres on cold start.

## Details
- **Service file:** `src/gilbert/core/services/radio_dj.py` — `RadioDJService`
- **Capabilities:** `radio_dj`, `ai_tools`
- **Required deps:** `music`, `speaker_control`, `scheduler`
- **Optional deps:** `presence`, `entity_storage`, `event_bus`, `configuration`
- **Config model:** `RadioDJConfig` in `src/gilbert/config.py`, namespace `radio_dj`
- **Config defaults in:** `gilbert.yaml` under `radio_dj:` section

### Genre Selection Algorithm
1. Gather likes from all present users → vote counter
2. Gather vetoes from all present users → exclusion set
3. Highest-voted non-vetoed genre wins
4. If all voted genres vetoed → fall back to default rotation (skipping vetoed)
5. If no preferences → cold-start rotation through `default_genres`
6. Throttle: `min_switch_interval` minutes between auto switches (bypassed on arrivals)

### Playback Path
`_play_genre(genre)` calls `music_svc.search(genre,
kind=MusicItemKind.PLAYLIST, limit=1)`. The first result is passed to
`music_svc.play_item(item, speaker_names=..., volume=...)` which
resolves the playable URI via the music backend and delegates to the
speaker service. On `MusicSearchUnavailableError` (e.g. Sonos SMAPI not
yet linked), the play is skipped and a warning is logged — the radio DJ
can't work until the admin runs the music service's "Link music service
for search" action.

### Storage Collections (namespaced `radio_dj.*`)
- `preferences` — per-user prefs (`prefs:{user_id}`): `likes`/`vetoes` (genre-level lists) plus `liked_tracks`/`vetoed_tracks` (lists of `{title, artist, album, uri}` dicts). Track-level prefs are populated by `like_current`/`dislike_current` when the music service can report what's actually playing via `MusicService.now_playing()`. Track-level filtering isn't wired into genre selection yet — the data is recorded but genre-level prefs still drive playback choice.
- `state` — DJ state persistence across restarts (`dj_state`)

### Events
- Subscribes to: `presence.arrived`, `presence.departed`
- Emits: `radio_dj.started`, `radio_dj.stopped`, `radio_dj.genre_changed`, `radio_dj.track_liked`, `radio_dj.track_vetoed`

### AI Tools
`radio_start`, `radio_stop`, `radio_request`, `radio_skip`, `radio_like`, `radio_dislike`, `radio_veto`, `radio_status`, `radio_set_preferences` (admin only). `radio_status` includes a `now_playing` block (title/artist/album/state/position) when the music service can report it.

### Scheduler Job
`radio-dj-poll` — system job running every `poll_interval` seconds, checks presence and rotates genres.

## Related
- `src/gilbert/core/services/music.py` — music search and playback
- `src/gilbert/core/services/speaker.py` — speaker control
- `src/gilbert/core/services/presence.py` — presence detection
- `tests/unit/test_radio_dj.py` — 49 unit tests
