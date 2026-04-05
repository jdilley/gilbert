# Service Registry (Legacy DI Container)

## Summary
Lightweight hand-rolled DI container. Maps interface types to concrete instances. Coexists with the newer ServiceManager — used for backward compat registrations of core components.

## Details
Located in `src/gilbert/core/registry.py`.

**ServiceRegistry** provides:
- `register(interface, implementation)` — bind a concrete instance to an interface type
- `get(interface) -> T` — retrieve implementation (raises `LookupError` if missing)
- `register_factory(interface, factory)` — lazy instantiation on first `get()`, then cached
- `has(interface) -> bool` — check if registered

**Role in app bootstrap**: Core services are managed by `ServiceManager`, but the registry holds backward-compat references to `StorageBackend`, `EventBus`, `DeviceManager`, and the `ServiceManager` itself.

**Relationship to ServiceManager**: ServiceRegistry is a static DI container (type → instance). ServiceManager handles lifecycle, capabilities, and dependency resolution. Plugins only receive the ServiceManager.

## Related
- `src/gilbert/core/registry.py` — ServiceRegistry
- `src/gilbert/core/service_manager.py` — the capability-aware ServiceManager
- [Service System](memory-service-system.md) — the newer service layer
- `tests/unit/test_registry.py` — 5 unit tests
