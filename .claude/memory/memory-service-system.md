# Service System

## Summary
Discoverable service layer where services declare capabilities and dependencies. The ServiceManager handles registration, topological dependency resolution, ordered startup, and runtime discovery. Failed services are skipped gracefully with cascade failure for dependents.

## Details

### Core Concepts
- **Service** (`src/gilbert/interfaces/service.py`) — ABC with `service_info()`, `start(resolver)`, `stop()`
- **ServiceInfo** — declares `name`, `capabilities` (what it provides), `requires` (must exist), `optional` (nice to have)
- **ServiceResolver** — read-only view passed to `start()` for pulling dependencies: `get_capability()`, `require_capability()`, `get_all()`
- **ServiceManager** (`src/gilbert/core/service_manager.py`) — implements ServiceResolver, handles lifecycle

### Capabilities
Capabilities are **strings**, not types. Examples: `"document_storage"`, `"event_bus"`, `"device_management"`. A service can provide multiple capabilities. Multiple services can provide the same capability. This enables flexible discovery ("find anything that provides weather").

### Lifecycle
1. Services are **registered** (constructed but not started)
2. Plugins load and register their own services
3. `start_all()` runs topological sort (Kahn's algorithm) on required capabilities
4. Each service starts in dependency order, receiving a `ServiceResolver`
5. Failed services → logged, added to `_failed`, dependents cascade-fail
6. Shutdown: `stop_all()` in reverse start order

### Core Service Wrappers (`src/gilbert/core/services/`)
Existing components are wrapped as services without modifying their ABCs:
- **StorageService** — wraps `StorageBackend`, provides `{"document_storage", "query_storage"}`
- **EventBusService** — wraps `EventBus`, provides `{"event_bus", "pub_sub"}`
- **DeviceManagerService** — provides `{"device_management", "device_registry"}`, requires `{"document_storage", "event_bus"}`

Each wrapper exposes the underlying component via a property (e.g., `storage_svc.backend`, `bus_svc.bus`).

### Relationship to ServiceRegistry
`ServiceManager` and `ServiceRegistry` coexist:
- **ServiceRegistry** — static DI container (type → instance), used for backward compat and non-service things
- **ServiceManager** — lifecycle-aware, capability-based discovery
- Both are available; plugins receive both in `setup(registry, *, services=None)`

### Boot Sequence (app.py)
1. Logging
2. Create ServiceManager
3. Register core services (StorageService, EventBusService, DeviceManagerService)
4. Register ServiceManager in old registry for backward compat
5. Load plugins → `plugin.setup(registry, services=service_manager)`
6. `service_manager.start_all()` — dependency resolution + ordered startup
7. Start integrations

## Related
- `src/gilbert/interfaces/service.py` — Service ABC, ServiceInfo, ServiceResolver
- `src/gilbert/core/service_manager.py` — ServiceManager implementation
- `src/gilbert/core/services/` — StorageService, EventBusService, DeviceManagerService
- `src/gilbert/core/app.py` — boot sequence using service system
- `tests/unit/test_service_manager.py` — 18 unit tests
- [Service Registry](memory-service-registry.md) — the legacy DI container that coexists
- [Plugin System](memory-plugin-system.md) — plugins register services via `setup()`
