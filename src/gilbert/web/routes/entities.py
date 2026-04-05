"""Entity browser route — browse collections and entities in storage."""

import json
from typing import Any

from fastapi import APIRouter, Request

from gilbert.core.app import Gilbert
from gilbert.interfaces.storage import Query, StorageBackend
from gilbert.web import templates

router = APIRouter(prefix="/entities")

PAGE_SIZE = 50


def _get_storage(gilbert: Gilbert) -> StorageBackend | None:
    """Get the storage backend from the service manager."""
    svc = gilbert.service_manager.get_by_capability("entity_storage")
    return svc.backend if svc else None  # type: ignore[union-attr]


@router.get("")
async def collections_list(request: Request) -> Any:
    """List all collections with entity counts."""
    gilbert: Gilbert = request.app.state.gilbert
    storage = _get_storage(gilbert)

    collections: list[dict[str, Any]] = []
    if storage is not None:
        names = await storage.list_collections()
        for name in sorted(names):
            count = await storage.count(Query(collection=name))
            collections.append({"name": name, "count": count})

    return templates.TemplateResponse(
        request, "entities.html", {"collections": collections}
    )


@router.get("/{collection}")
async def collection_detail(
    request: Request, collection: str, page: int = 1
) -> Any:
    """Browse entities within a collection."""
    gilbert: Gilbert = request.app.state.gilbert
    storage = _get_storage(gilbert)

    entities: list[dict[str, Any]] = []
    total = 0
    if storage is not None:
        total = await storage.count(Query(collection=collection))
        offset = (page - 1) * PAGE_SIZE
        results = await storage.query(
            Query(collection=collection, limit=PAGE_SIZE, offset=offset)
        )
        entities = results

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return templates.TemplateResponse(
        request,
        "collection.html",
        {
            "collection": collection,
            "entities": entities,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "page_size": PAGE_SIZE,
        },
    )


@router.get("/{collection}/{entity_id:path}")
async def entity_detail(request: Request, collection: str, entity_id: str) -> Any:
    """View a single entity's full data."""
    gilbert: Gilbert = request.app.state.gilbert
    storage = _get_storage(gilbert)

    entity: dict[str, Any] | None = None
    if storage is not None:
        entity = await storage.get(collection, entity_id)

    formatted = json.dumps(entity, indent=2, default=str) if entity else None

    return templates.TemplateResponse(
        request,
        "entity.html",
        {
            "collection": collection,
            "entity_id": entity_id,
            "entity": entity,
            "formatted": formatted,
        },
    )
