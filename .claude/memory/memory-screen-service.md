# Screen Service

## Summary
Remote display screens controlled by AI. Browser tabs connect via SSE, receive push events for documents, text, images, and control signals.

## Details

### Architecture
Single `ScreenService` at `src/gilbert/core/services/screens.py` combines:
- **Screen registry** — in-memory dict of `ConnectedScreen` objects, each with an `asyncio.Queue` for SSE events
- **Temp file management** — UUID-tokened files in `.gilbert/output/screens/` with TTL-based cleanup via scheduler
- **AI tool provider** — single `display` tool with actions: `show_document`, `show_text`, `show_images`, `list_screens`, `clear`

### Capabilities
- `screen_display`, `ai_tools`
- Optional deps: `knowledge`, `scheduler`, `event_bus`, `configuration`
- No hard requirements — works standalone

### SSE Push (not WebSocket)
Uses dedicated SSE endpoint at `/screens/stream` rather than the WebSocket event bus. Reasons:
- Screen content payloads shouldn't broadcast to all WebSocket clients
- SSE is simpler for unidirectional push
- Screen page is standalone (doesn't extend `base.html`)

Lightweight events (`screen.connected`, `screen.disconnected`) still go on the event bus.

### Screen Name Resolution
Strips suffixes (`screen`, `tv`, `display`, `monitor`, `panel`), strips possessives (`'s`), then does exact match followed by `difflib.get_close_matches`. Allows natural speech: "show X on the battery assembly screen".

### Web Routes (`src/gilbert/web/routes/screens.py`)
- `GET /screens` — standalone HTML page (no auth required)
- `GET /screens/stream?name=...` — SSE endpoint
- `GET /screens/api` — list screens (requires `user` role)
- `GET /screens/tmp/{token}` — serve temp files (no auth, UUID tokens)

### Template (`src/gilbert/web/templates/screens.html`)
Standalone page (not extending `base.html`) with states: setup, idle, default-url, loading, error, display. Client-side markdown rendering, PDF iframe display, image gallery grid.

### Configuration
```yaml
screens:
  enabled: true
  tmp_ttl_seconds: 1800
  cleanup_interval_seconds: 300
```

### Auth
`/screens` and `/screens/` added to `_PUBLIC_EXACT`/`_PUBLIC_PREFIXES` in `auth.py`. Screen stream and tmp paths added to tunnel public prefixes.

## Related
- [Knowledge Service](memory-knowledge-service.md) — document search integration
- [Scheduler Service](memory-scheduler-service.md) — periodic temp file cleanup
- `src/gilbert/core/services/screens.py` — main service
- `src/gilbert/web/routes/screens.py` — HTTP routes
- `src/gilbert/web/templates/screens.html` — display page
- `tests/unit/test_screen_service.py` — 50 unit tests
