# Event System

## Summary
Async pub/sub event bus for decoupled communication between components. Supports exact-match and glob-pattern subscriptions.

## Details
**Interface** (`src/gilbert/interfaces/events.py`):
- `Event` — frozen dataclass with `event_type` (dot-namespaced string), `data` (dict), `source` (optional device/component ID), `timestamp`
- `EventBus` ABC — `subscribe(event_type, handler)`, `publish(event)`, `subscribe_pattern(pattern, handler)`
- `subscribe` and `subscribe_pattern` return an unsubscribe callable
- `EventHandler` = `Callable[[Event], Awaitable[None]]`

**Implementation** (`src/gilbert/core/events.py`):
- `InMemoryEventBus` — in-process async event bus
- Handlers run concurrently via `asyncio.gather`
- Handler errors are logged but never crash the bus or affect other handlers
- Pattern matching uses `fnmatch` (e.g., `"device.*"` matches `"device.state_changed"`)

**Event type conventions** (dot-namespaced):
- `device.added`, `device.removed`, `device.state_changed`
- `integration.connected`, `integration.disconnected`
- `automation.triggered`

No enum for event types — extensibility is more important. Plugins can define their own event namespaces.

## Related
- `src/gilbert/interfaces/events.py` — Event, EventBus ABC
- `src/gilbert/core/events.py` — InMemoryEventBus
- `src/gilbert/core/device_manager.py` — publishes device events
- `tests/unit/test_events.py` — 8 unit tests
