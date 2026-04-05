"""Storage service — wraps StorageBackend as a discoverable service."""

from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver
from gilbert.interfaces.storage import StorageBackend


class StorageService(Service):
    """Exposes a StorageBackend as a service with document_storage capability."""

    def __init__(self, backend: StorageBackend) -> None:
        self._backend = backend

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="storage",
            capabilities=frozenset({"document_storage", "query_storage"}),
        )

    @property
    def backend(self) -> StorageBackend:
        return self._backend

    async def stop(self) -> None:
        await self._backend.close()
