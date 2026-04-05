# Multi-backend Aggregator Pattern

## Summary
Architectural decision: when a capability can have multiple implementations, use a single aggregator service that holds N backends internally, rather than registering multiple services with the same capability.

## Details
**Pattern**: A single service (e.g., `PresenceService`) registers the capability (`"presence"`) and internally holds a list of backend implementations (e.g., `PresenceBackend` ABCs — UniFi, Bluetooth, camera). It merges/ranks results from all backends and presents a unified answer to callers.

**Why**: Keeps consumer-side simple. Merging/ranking logic lives in one place per capability rather than being duplicated across every caller. Already proven with `TTSService` wrapping `TTSBackend`.

**How to apply**: When designing a new service that could have multiple providers, define a backend ABC, build one aggregator service that holds N backends, and register that single service. Don't register multiple services with the same capability expecting callers to combine results.

## Related
- `src/gilbert/core/services/tts.py` — TTSService wrapping TTSBackend (example of this pattern)
- `src/gilbert/interfaces/tts.py` — TTSBackend ABC
