"""Tests for PersonaService — persona storage, editing, and defaults."""

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from gilbert.core.services.persona import DEFAULT_PERSONA, PersonaService
from gilbert.core.services.storage import StorageService
from gilbert.interfaces.service import ServiceResolver
from gilbert.interfaces.storage import StorageBackend


class StubStorageBackend(StorageBackend):
    """Minimal in-memory storage for persona tests."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def put(self, collection: str, entity_id: str, data: dict[str, Any]) -> None:
        self._data.setdefault(collection, {})[entity_id] = {"_id": entity_id, **data}

    async def get(self, collection: str, entity_id: str) -> dict[str, Any] | None:
        return self._data.get(collection, {}).get(entity_id)

    async def delete(self, collection: str, entity_id: str) -> None:
        self._data.get(collection, {}).pop(entity_id, None)

    async def exists(self, collection: str, entity_id: str) -> bool:
        return entity_id in self._data.get(collection, {})

    async def query(self, query: Any) -> list[dict[str, Any]]:
        return list(self._data.get(query.collection, {}).values())

    async def count(self, query: Any) -> int:
        return len(await self.query(query))

    async def list_collections(self) -> list[str]:
        return list(self._data.keys())

    async def drop_collection(self, collection: str) -> None:
        self._data.pop(collection, None)

    async def ensure_index(self, index: Any) -> None:
        pass

    async def list_indexes(self, collection: str) -> list[Any]:
        return []

    async def ensure_foreign_key(self, fk: Any) -> None:
        pass

    async def list_foreign_keys(self, collection: str) -> list[Any]:
        return []


@pytest.fixture
def stub_storage() -> StubStorageBackend:
    return StubStorageBackend()


@pytest.fixture
def storage_service(stub_storage: StubStorageBackend) -> StorageService:
    return StorageService(stub_storage)


@pytest.fixture
def resolver(storage_service: StorageService) -> ServiceResolver:
    mock = AsyncMock(spec=ServiceResolver)

    def require_cap(cap: str) -> Any:
        if cap == "entity_storage":
            return storage_service
        raise LookupError(cap)

    mock.require_capability.side_effect = require_cap
    mock.get_capability.return_value = None
    return mock


@pytest.fixture
def service() -> PersonaService:
    return PersonaService()


# --- Service info ---


def test_service_info(service: PersonaService) -> None:
    info = service.service_info()
    assert info.name == "persona"
    assert "persona" in info.capabilities
    assert "ai_tools" in info.capabilities
    assert "entity_storage" in info.requires


# --- Lifecycle ---


async def test_start_uses_default_when_no_saved(
    service: PersonaService, resolver: ServiceResolver
) -> None:
    await service.start(resolver)
    assert service.persona == DEFAULT_PERSONA
    assert service.is_customized is False


async def test_start_loads_saved_persona(
    service: PersonaService, resolver: ServiceResolver, stub_storage: StubStorageBackend
) -> None:
    await stub_storage.put("gilbert.persona", "active", {
        "text": "Custom persona text",
        "customized": True,
    })
    await service.start(resolver)
    assert service.persona == "Custom persona text"
    assert service.is_customized is True


# --- Update ---


async def test_update_persona(
    service: PersonaService, resolver: ServiceResolver, stub_storage: StubStorageBackend
) -> None:
    await service.start(resolver)
    await service.update_persona("Be a pirate.")
    assert service.persona == "Be a pirate."
    assert service.is_customized is True

    saved = await stub_storage.get("gilbert.persona", "active")
    assert saved is not None
    assert saved["text"] == "Be a pirate."
    assert saved["customized"] is True


async def test_reset_persona(
    service: PersonaService, resolver: ServiceResolver, stub_storage: StubStorageBackend
) -> None:
    await service.start(resolver)
    await service.update_persona("Custom")
    await service.reset_persona()
    assert service.persona == DEFAULT_PERSONA
    assert service.is_customized is False

    saved = await stub_storage.get("gilbert.persona", "active")
    assert saved is not None
    assert saved["customized"] is False


# --- Tools ---


def test_tool_provider_name(service: PersonaService) -> None:
    assert service.tool_provider_name == "persona"


def test_get_tools(service: PersonaService) -> None:
    tools = service.get_tools()
    names = [t.name for t in tools]
    assert "get_persona" in names
    assert "update_persona" in names
    assert "reset_persona" in names


async def test_tool_get_persona(
    service: PersonaService, resolver: ServiceResolver
) -> None:
    await service.start(resolver)
    result = await service.execute_tool("get_persona", {})
    parsed = json.loads(result)
    assert parsed["persona"] == DEFAULT_PERSONA


async def test_tool_update_persona(
    service: PersonaService, resolver: ServiceResolver
) -> None:
    await service.start(resolver)
    result = await service.execute_tool("update_persona", {"text": "Be helpful."})
    parsed = json.loads(result)
    assert parsed["status"] == "updated"
    assert service.persona == "Be helpful."
    assert service.is_customized is True


async def test_tool_reset_persona(
    service: PersonaService, resolver: ServiceResolver
) -> None:
    await service.start(resolver)
    await service.update_persona("Custom")
    result = await service.execute_tool("reset_persona", {})
    parsed = json.loads(result)
    assert parsed["status"] == "reset"
    assert service.persona == DEFAULT_PERSONA
    assert service.is_customized is False


async def test_tool_unknown_raises(
    service: PersonaService, resolver: ServiceResolver
) -> None:
    await service.start(resolver)
    with pytest.raises(KeyError, match="Unknown tool"):
        await service.execute_tool("nonexistent", {})
