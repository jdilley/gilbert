"""Entity browser route — browse collections and entities in storage."""

import json
from typing import Any

from fastapi import APIRouter, Depends, Request

from gilbert.core.app import Gilbert
from gilbert.interfaces.auth import UserContext
from gilbert.web.auth import require_role
from gilbert.interfaces.storage import Query, StorageBackend
from gilbert.web import templates

router = APIRouter(prefix="/entities")

PAGE_SIZE = 50


def _get_raw_storage(gilbert: Gilbert) -> StorageBackend | None:
    """Get the raw (un-namespaced) storage backend."""
    svc = gilbert.service_manager.get_by_capability("entity_storage")
    return getattr(svc, "raw_backend", None) if svc else None


def _group_by_namespace(
    collections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group collections by namespace prefix.

    Returns a list of namespace groups, each with a name and collections list.
    Collections without a recognized namespace go under "other".
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for col in collections:
        name = col["name"]
        # Split on "." to find namespace: "gilbert.foo" -> "gilbert", "foo"
        parts = name.split(".", 1)
        if len(parts) == 2:
            ns = parts[0]
            # Check for deeper plugin namespace: "gilbert.plugin.name.collection"
            if ns == "gilbert" and parts[1].startswith("plugin."):
                rest = parts[1][len("plugin."):]  # "name.collection"
                plugin_parts = rest.split(".", 1)
                if len(plugin_parts) == 2:
                    ns = f"gilbert.plugin.{plugin_parts[0]}"
                    col = {**col, "short_name": plugin_parts[1]}
                else:
                    col = {**col, "short_name": rest}
            else:
                col = {**col, "short_name": parts[1]}
        else:
            ns = "other"
            col = {**col, "short_name": name}
        groups.setdefault(ns, []).append(col)

    # Sort: "gilbert" first, then "gilbert.plugin.*", then "other" last
    def ns_sort_key(ns: str) -> tuple[int, str]:
        if ns == "gilbert":
            return (0, ns)
        if ns.startswith("gilbert.plugin."):
            return (1, ns)
        return (2, ns)

    return [
        {"namespace": ns, "collections": sorted(cols, key=lambda c: c["short_name"])}
        for ns, cols in sorted(groups.items(), key=lambda x: ns_sort_key(x[0]))
    ]


@router.get("")
async def collections_list(request: Request, user: UserContext = Depends(require_role("admin"))) -> Any:
    """List all collections with entity counts, grouped by namespace."""
    gilbert: Gilbert = request.app.state.gilbert
    storage = _get_raw_storage(gilbert)

    collections: list[dict[str, Any]] = []
    if storage is not None:
        names = await storage.list_collections()
        for name in sorted(names):
            count = await storage.count(Query(collection=name))
            collections.append({"name": name, "count": count})

    groups = _group_by_namespace(collections)

    return templates.TemplateResponse(
        request, "entities.html", {"groups": groups, "total_collections": len(collections)}
    )


@router.get("/{collection}")
async def collection_detail(
    request: Request, collection: str, page: int = 1,
    user: UserContext = Depends(require_role("admin")),
) -> Any:
    """Browse entities within a collection."""
    gilbert: Gilbert = request.app.state.gilbert
    storage = _get_raw_storage(gilbert)

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
async def entity_detail(request: Request, collection: str, entity_id: str, user: UserContext = Depends(require_role("admin"))) -> Any:
    """View a single entity's full data."""
    gilbert: Gilbert = request.app.state.gilbert
    storage = _get_raw_storage(gilbert)

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
