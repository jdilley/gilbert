"""JSON API routes for the React SPA frontend.

Each endpoint mirrors data that was previously rendered into Jinja2 templates.
The existing HTML routes are left untouched for backward compatibility.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from gilbert.core.app import Gilbert
from gilbert.interfaces.auth import UserContext
from gilbert.interfaces.storage import Filter, FilterOp, Query, SortField, StorageBackend
from gilbert.interfaces.tools import ToolProvider
from gilbert.web.auth import get_user_context, require_role

router = APIRouter(prefix="/api", tags=["api"])

PAGE_SIZE = 50


# ---- helpers ----


def _gilbert(request: Request) -> Gilbert:
    return request.app.state.gilbert  # type: ignore[no-any-return]


def _get_acl(gilbert: Gilbert) -> Any:
    svc = gilbert.service_manager.get_by_capability("access_control")
    if svc is None:
        raise HTTPException(status_code=503, detail="Access control service not available")
    return svc


def _get_raw_storage(gilbert: Gilbert) -> StorageBackend | None:
    svc = gilbert.service_manager.get_by_capability("entity_storage")
    return getattr(svc, "raw_backend", None) if svc else None


# ---- Auth ----


@router.get("/auth/methods")
async def auth_methods(request: Request) -> list[dict[str, Any]]:
    """Return available login methods as JSON."""
    gilbert = _gilbert(request)
    auth_svc = gilbert.service_manager.get_by_capability("authentication")
    if auth_svc is None:
        return []
    methods = auth_svc.get_login_methods()
    return [
        {
            "provider_type": m.provider_type,
            "display_name": m.display_name,
            "method": m.method,
            "redirect_url": m.redirect_url,
            "form_action": m.form_action,
        }
        for m in methods
    ]


# ---- Dashboard ----


_ALL_CARDS = [
    {"title": "Chat", "description": "Talk to Gilbert and get things done.", "url": "/chat", "icon": "&#128172;", "required_role": "everyone", "requires_capability": "ai_chat"},
    {"title": "Documents", "description": "Browse and search the document knowledge store.", "url": "/documents", "icon": "&#128196;", "required_role": "user", "requires_capability": "knowledge"},
    {"title": "Screens", "description": "Set up remote display screens for documents and content.", "url": "/screens", "icon": "&#128187;", "required_role": "everyone", "requires_capability": "screen_display"},
    {"title": "Roles & Access", "description": "Manage roles, user permissions, and tool access.", "url": "/roles", "icon": "&#128274;", "required_role": "admin"},
    {"title": "System Browser", "description": "View services, capabilities, configuration, and tools.", "url": "/system", "icon": "&#9881;", "required_role": "admin"},
    {"title": "Inbox", "description": "Browse and manage email messages.", "url": "/inbox", "icon": "&#9993;", "required_role": "admin", "requires_capability": "email"},
    {"title": "Entity Browser", "description": "Browse collections and entities in storage.", "url": "/entities", "icon": "&#128451;", "required_role": "admin"},
]


def _get_effective_level(gilbert: Gilbert, user: UserContext) -> int:
    _BUILTIN = {"admin": 0, "user": 100, "everyone": 200}
    acl_svc = gilbert.service_manager.get_by_capability("access_control")
    if acl_svc is not None:
        return acl_svc.get_effective_level(user)  # type: ignore[no-any-return]
    if not user.roles:
        return 200
    return min(_BUILTIN.get(r, 100) for r in user.roles)


def _get_role_level(gilbert: Gilbert, role: str) -> int:
    _BUILTIN = {"admin": 0, "user": 100, "everyone": 200}
    acl_svc = gilbert.service_manager.get_by_capability("access_control")
    if acl_svc is not None:
        return acl_svc.get_role_level(role)  # type: ignore[no-any-return]
    return _BUILTIN.get(role, 100)


@router.get("/dashboard")
async def dashboard(
    request: Request,
    user: UserContext = Depends(get_user_context),  # noqa: B008
) -> dict[str, Any]:
    gilbert = _gilbert(request)
    effective = _get_effective_level(gilbert, user)
    if effective < 0:
        effective = 200
    sm = gilbert.service_manager
    cards = []
    for card in _ALL_CARDS:
        if effective > _get_role_level(gilbert, card["required_role"]):
            continue
        cap = card.get("requires_capability")
        if cap and sm.get_by_capability(cap) is None:
            continue
        cards.append(card)
    return {"cards": cards}


# ---- Documents ----


def _build_tree_nodes(tree: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert internal tree to serializable node list."""
    nodes: list[dict[str, Any]] = []
    for folder_name, subtree in sorted(tree.get("_folders", {}).items()):
        nodes.append({
            "name": folder_name,
            "path": folder_name,
            "is_folder": True,
            "children": _build_tree_nodes(subtree),
        })
    for doc in tree.get("_files", []):
        nodes.append({
            "name": doc.get("name", ""),
            "path": doc.get("path", ""),
            "is_folder": False,
            "size": doc.get("size"),
            "modified": doc.get("modified", ""),
            "added": doc.get("added_at", ""),
            "indexed": doc.get("indexed_at", ""),
            "external_url": doc.get("url", "") if doc.get("external") else None,
        })
    return nodes


def _build_doc_tree(documents: list[dict[str, Any]]) -> dict[str, Any]:
    tree: dict[str, Any] = {"_files": [], "_folders": {}}
    for doc in documents:
        parts = doc["path"].split("/")
        node = tree
        for folder in parts[:-1]:
            if folder not in node["_folders"]:
                node["_folders"][folder] = {"_files": [], "_folders": {}}
            node = node["_folders"][folder]
        node["_files"].append(doc)
    return tree


@router.get("/documents")
async def documents_list(
    request: Request,
    user: UserContext = Depends(require_role("user")),  # noqa: B008
) -> dict[str, Any]:
    gilbert = _gilbert(request)
    knowledge = gilbert.service_manager.get_by_capability("knowledge")
    if knowledge is None:
        return {"sources": []}

    storage_svc = gilbert.service_manager.get_by_capability("entity_storage")
    storage = getattr(storage_svc, "backend", None) if storage_svc else None

    tracking_map: dict[str, dict[str, Any]] = {}
    if storage:
        try:
            all_tracking = await storage.query(Query(collection="knowledge_documents"))
            tracking_map = {t.get("document_id", ""): t for t in all_tracking}
        except Exception:
            pass

    sources: list[dict[str, Any]] = []
    for backend in knowledge.backends.values():
        all_docs: list[dict[str, Any]] = []
        for doc_id, tracking in tracking_map.items():
            if tracking.get("source_id") != backend.source_id:
                continue
            all_docs.append({
                "document_id": doc_id,
                "name": tracking.get("name", ""),
                "path": tracking.get("path", ""),
                "source_id": tracking.get("source_id", ""),
                "type": tracking.get("type", ""),
                "size": tracking.get("size_bytes", 0),
                "modified": tracking.get("last_modified", ""),
                "added_at": tracking.get("added_at", ""),
                "indexed_at": tracking.get("indexed_at", ""),
                "url": tracking.get("external_url", "") or f"/documents/serve/{tracking.get('source_id', '')}/{tracking.get('path', '')}",
                "external": bool(tracking.get("external_url", "")),
            })

        if not all_docs:
            try:
                docs = await backend.list_documents()
                for d in docs:
                    all_docs.append({
                        "document_id": d.document_id,
                        "name": d.name,
                        "path": d.path,
                        "source_id": d.source_id,
                        "type": d.document_type.value,
                        "size": d.size_bytes,
                        "modified": d.last_modified,
                        "added_at": "",
                        "indexed_at": "",
                        "url": d.external_url or f"/documents/serve/{d.source_id}/{d.path}",
                        "external": bool(d.external_url),
                    })
            except Exception:
                pass

        tree = _build_doc_tree(all_docs)
        sources.append({
            "source_id": backend.source_id,
            "source_name": backend.display_name,
            "tree": _build_tree_nodes(tree),
        })

    return {"sources": sources}


@router.get("/documents/search")
async def documents_search(
    request: Request,
    q: str = "",
    source: str | None = None,
    user: UserContext = Depends(require_role("user")),  # noqa: B008
) -> dict[str, Any]:
    gilbert = _gilbert(request)
    knowledge = gilbert.service_manager.get_by_capability("knowledge")
    if knowledge is None or not q:
        return {"results": []}

    tracking_map: dict[str, dict[str, Any]] = {}
    storage_svc = gilbert.service_manager.get_by_capability("entity_storage")
    if storage_svc is not None:
        storage = getattr(storage_svc, "backend", None)
        if storage:
            try:
                all_tracking = await storage.query(Query(collection="knowledge_documents"))
                tracking_map = {t.get("document_id", ""): t for t in all_tracking}
            except Exception:
                pass

    response = await knowledge.search(q, n_results=10, source_filter=source)
    results = []
    for r in response.results:
        results.append({
            "document_name": r.name,
            "source_id": r.source_id,
            "relevance": r.relevance_score,
            "chunk_text": r.chunk_text[:300] + ("..." if len(r.chunk_text) > 300 else ""),
            "page_number": r.page_number,
            "doc_type": r.document_type.value,
        })

    return {"results": results}


# ---- Entities ----


async def _get_sortable_fields(storage: StorageBackend, collection: str) -> list[str]:
    fields: set[str] = {"_id"}
    try:
        indexes = await storage.list_indexes(collection)
        for idx in indexes:
            for f in idx.fields:
                fields.add(f)
    except Exception:
        pass
    try:
        fks = await storage.list_foreign_keys(collection)
        for fk in fks:
            if fk.collection == collection:
                fields.add(fk.field)
    except Exception:
        pass
    return sorted(fields)


async def _get_fk_map(storage: StorageBackend, collection: str) -> dict[str, str]:
    """Map of field -> ref_collection for FK fields."""
    fk_map: dict[str, str] = {}
    try:
        fks = await storage.list_foreign_keys(collection)
        for fk in fks:
            if fk.collection == collection:
                fk_map[fk.field] = fk.ref_collection
    except Exception:
        pass
    return fk_map


def _group_by_namespace(collections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for col in collections:
        name = col["name"]
        parts = name.split(".", 1)
        if len(parts) == 2:
            ns = parts[0]
            if ns == "gilbert" and parts[1].startswith("plugin."):
                rest = parts[1][len("plugin."):]
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


@router.get("/entities")
async def entities_list(
    request: Request,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, Any]:
    gilbert = _gilbert(request)
    storage = _get_raw_storage(gilbert)

    collections: list[dict[str, Any]] = []
    if storage is not None:
        names = await storage.list_collections()
        for name in sorted(names):
            count = await storage.count(Query(collection=name))
            collections.append({"name": name, "count": count})

    return {"groups": _group_by_namespace(collections)}


@router.get("/entities/{collection}")
async def entities_collection(
    request: Request,
    collection: str,
    page: int = 1,
    sort: str = "",
    dir: str = "",
    filter_field: str = "",
    filter_op: str = "eq",
    filter_value: str = "",
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, Any]:
    gilbert = _gilbert(request)
    storage = _get_raw_storage(gilbert)

    entities: list[dict[str, Any]] = []
    total = 0
    sortable_fields: list[str] = ["_id"]
    fk_map: dict[str, str] = {}

    if storage is not None:
        sortable_fields = await _get_sortable_fields(storage, collection)
        fk_map = await _get_fk_map(storage, collection)

        sort_fields: list[SortField] = []
        if sort:
            sort_fields = [SortField(field=sort, descending=(dir == "desc"))]

        filters: list[Filter] = []
        if filter_field and filter_op:
            try:
                op = FilterOp(filter_op)
                if op == FilterOp.EXISTS:
                    filters = [Filter(field=filter_field, op=op)]
                elif filter_value:
                    value: Any = filter_value
                    if op in (FilterOp.GT, FilterOp.GTE, FilterOp.LT, FilterOp.LTE):
                        try:
                            value = float(filter_value)
                            if value == int(value):
                                value = int(value)
                        except ValueError:
                            pass
                    filters = [Filter(field=filter_field, op=op, value=value)]
            except ValueError:
                pass

        total = await storage.count(Query(collection=collection, filters=filters))
        offset = (page - 1) * PAGE_SIZE
        entities = await storage.query(
            Query(collection=collection, filters=filters, sort=sort_fields, limit=PAGE_SIZE, offset=offset)
        )

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return {
        "collection": collection,
        "entities": entities,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "sortable_fields": sortable_fields,
        "fk_map": fk_map,
    }


@router.get("/entities/{collection}/{entity_id:path}")
async def entities_detail(
    request: Request,
    collection: str,
    entity_id: str,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, Any]:
    gilbert = _gilbert(request)
    storage = _get_raw_storage(gilbert)

    entity: dict[str, Any] | None = None
    fk_map: dict[str, str] = {}
    if storage is not None:
        entity = await storage.get(collection, entity_id)
        fk_map = await _get_fk_map(storage, collection)

    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    return {
        "collection": collection,
        "entity_id": entity_id,
        "entity": json.loads(json.dumps(entity, default=str)),
        "fk_map": fk_map,
    }


# ---- Roles ----


@router.get("/roles")
async def roles_list(
    request: Request,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, Any]:
    acl = _get_acl(_gilbert(request))
    roles = await acl.list_roles()
    return {
        "roles": [
            {
                "name": r["name"],
                "level": r["level"],
                "description": r.get("description", ""),
                "builtin": r.get("builtin", False),
            }
            for r in roles
        ],
    }


@router.post("/roles/create")
async def create_role(
    request: Request,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, str]:
    body = await request.json()
    acl = _get_acl(_gilbert(request))
    await acl.create_role(
        name=body["name"], level=body["level"], description=body.get("description", ""),
    )
    return {"status": "ok"}


@router.post("/roles/{role_name}/update")
async def update_role(
    request: Request,
    role_name: str,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, str]:
    body = await request.json()
    acl = _get_acl(_gilbert(request))
    await acl.update_role(name=role_name, level=body["level"], description=body.get("description", ""))
    return {"status": "ok"}


@router.post("/roles/{role_name}/delete")
async def delete_role(
    request: Request,
    role_name: str,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, str]:
    acl = _get_acl(_gilbert(request))
    await acl.delete_role(role_name)
    return {"status": "ok"}


# ---- Tool Permissions ----


@router.get("/roles/tools")
async def tool_permissions(
    request: Request,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, Any]:
    gilbert = _gilbert(request)
    acl = _get_acl(gilbert)

    sm = gilbert.service_manager
    tools: list[dict[str, Any]] = []
    for name in sm.started_services:
        svc = sm._registered.get(name)
        if svc is not None and isinstance(svc, ToolProvider):
            for tool_def in svc.get_tools():
                override = acl._tool_overrides.get(tool_def.name)
                tools.append({
                    "provider": svc.tool_provider_name,
                    "tool_name": tool_def.name,
                    "default_role": tool_def.required_role,
                    "effective_role": override or tool_def.required_role,
                    "has_override": override is not None,
                })
    tools.sort(key=lambda t: (t["provider"], t["tool_name"]))

    roles = await acl.list_roles()
    return {"tools": tools, "role_names": [r["name"] for r in roles]}


@router.post("/roles/tools/{tool_name}/set")
async def set_tool_role(
    request: Request,
    tool_name: str,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, str]:
    body = await request.json()
    acl = _get_acl(_gilbert(request))
    await acl.set_tool_override(tool_name, body["role"])
    return {"status": "ok"}


@router.post("/roles/tools/{tool_name}/clear")
async def clear_tool_role(
    request: Request,
    tool_name: str,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, str]:
    acl = _get_acl(_gilbert(request))
    await acl.clear_tool_override(tool_name)
    return {"status": "ok"}


# ---- AI Profiles ----


@router.get("/roles/profiles")
async def ai_profiles(
    request: Request,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, Any]:
    gilbert = _gilbert(request)
    ai_svc = gilbert.service_manager.get_by_capability("ai_chat")
    if ai_svc is None:
        return {"profiles": [], "declared_calls": [], "profile_names": [], "all_tool_names": []}

    profiles = ai_svc.list_profiles()
    assignments = ai_svc.list_assignments()

    sm = gilbert.service_manager
    declared_calls: list[str] = []
    for svc_name in sm.started_services:
        svc = sm._registered.get(svc_name)
        if svc is not None:
            info = svc.service_info()
            declared_calls.extend(sorted(info.ai_calls))
    for call_name in sorted(assignments):
        if call_name not in declared_calls:
            declared_calls.append(call_name)

    all_tool_names: list[str] = []
    for svc_name in sm.started_services:
        svc = sm._registered.get(svc_name)
        if svc is not None and isinstance(svc, ToolProvider):
            for tool_def in svc.get_tools():
                all_tool_names.append(tool_def.name)
    all_tool_names.sort()

    return {
        "profiles": [
            {
                "name": p.name,
                "description": p.description,
                "tool_mode": p.tool_mode,
                "tools": p.tools,
                "tool_roles": p.tool_roles,
                "assigned_calls": [
                    c for c in declared_calls if assignments.get(c) == p.name
                ],
            }
            for p in profiles
        ],
        "declared_calls": declared_calls,
        "profile_names": [p.name for p in profiles],
        "all_tool_names": all_tool_names,
    }


@router.post("/roles/profiles/save")
async def save_profile(
    request: Request,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, str]:
    from gilbert.core.services.ai import AIContextProfile

    gilbert = _gilbert(request)
    ai_svc = gilbert.service_manager.get_by_capability("ai_chat")
    if ai_svc is None:
        raise HTTPException(status_code=503, detail="AI service not available")

    body = await request.json()
    existing = ai_svc._profiles.get(body["name"])
    existing_tool_roles = existing.tool_roles if existing else {}

    profile = AIContextProfile(
        name=body["name"],
        description=body.get("description", ""),
        tool_mode=body.get("tool_mode", "all"),
        tools=body.get("tools", []),
        tool_roles=body.get("tool_roles", existing_tool_roles),
    )
    await ai_svc.set_profile(profile)
    return {"status": "ok"}


@router.post("/roles/profiles/{profile_name}/delete")
async def delete_profile(
    request: Request,
    profile_name: str,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, str]:
    gilbert = _gilbert(request)
    ai_svc = gilbert.service_manager.get_by_capability("ai_chat")
    if ai_svc is None:
        raise HTTPException(status_code=503, detail="AI service not available")
    await ai_svc.delete_profile(profile_name)
    return {"status": "ok"}


@router.post("/roles/profiles/assign")
async def assign_profile(
    request: Request,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, str]:
    gilbert = _gilbert(request)
    ai_svc = gilbert.service_manager.get_by_capability("ai_chat")
    if ai_svc is None:
        raise HTTPException(status_code=503, detail="AI service not available")
    body = await request.json()
    await ai_svc.set_assignment(body["ai_call"], body["profile_name"])
    return {"status": "ok"}


# ---- User Roles ----


@router.get("/roles/users")
async def user_roles(
    request: Request,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, Any]:
    gilbert = _gilbert(request)
    acl = _get_acl(gilbert)

    user_svc = gilbert.service_manager.get_by_capability("users")
    if user_svc is None:
        return {"users": [], "role_names": []}

    users = await user_svc.list_users()
    roles = await acl.list_roles()

    return {
        "users": [
            {
                "user_id": u.get("_id", u.get("user_id", "")),
                "email": u.get("email", ""),
                "display_name": u.get("display_name", ""),
                "roles": u.get("roles", []),
            }
            for u in users
        ],
        "role_names": [r["name"] for r in roles],
    }


@router.post("/roles/users/{user_id}/roles")
async def set_user_roles(
    request: Request,
    user_id: str,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, str]:
    gilbert = _gilbert(request)
    user_svc = gilbert.service_manager.get_by_capability("users")
    if user_svc is None:
        raise HTTPException(status_code=503, detail="User service not available")
    body = await request.json()
    await user_svc.backend.update_user(user_id, {"roles": sorted(body["roles"])})
    return {"status": "ok"}


# ---- Collection ACLs ----


@router.get("/roles/collections")
async def collection_acls(
    request: Request,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, Any]:
    gilbert = _gilbert(request)
    acl = _get_acl(gilbert)

    storage_svc = gilbert.service_manager.get_by_capability("entity_storage")
    collections: list[str] = []
    if storage_svc is not None:
        collections = await storage_svc.backend.list_collections()

    acl_entries = []
    for col in sorted(collections):
        entry = acl._collection_acl.get(col)
        acl_entries.append({
            "collection": col,
            "read_role": entry["read_role"] if entry else "user",
            "write_role": entry["write_role"] if entry else "admin",
            "has_custom": entry is not None,
        })

    roles = await acl.list_roles()
    return {"collections": acl_entries, "role_names": [r["name"] for r in roles]}


@router.post("/roles/collections/{collection}/set")
async def set_collection_acl(
    request: Request,
    collection: str,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, str]:
    body = await request.json()
    acl = _get_acl(_gilbert(request))
    await acl.set_collection_acl(collection, read_role=body["read_role"], write_role=body["write_role"])
    return {"status": "ok"}


@router.post("/roles/collections/{collection}/clear")
async def clear_collection_acl(
    request: Request,
    collection: str,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, str]:
    acl = _get_acl(_gilbert(request))
    await acl.clear_collection_acl(collection)
    return {"status": "ok"}


# ---- System ----


@router.get("/system")
async def system_services(
    request: Request,
    user: UserContext = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, Any]:
    from gilbert.interfaces.configuration import Configurable
    from gilbert.core.services.configuration import ConfigurationService

    gilbert = _gilbert(request)
    sm = gilbert.service_manager
    config_svc = sm.get_by_capability("configuration")

    services: list[dict[str, Any]] = []
    for name in list(sm._registered.keys()):
        svc = sm._registered[name]
        info = svc.service_info()
        started = name in sm.started_services
        failed = name in sm.failed_services

        entry: dict[str, Any] = {
            "name": info.name,
            "capabilities": sorted(info.capabilities),
            "requires": sorted(info.requires),
            "optional": sorted(info.optional),
            "ai_calls": sorted(info.ai_calls),
            "events": sorted(info.events),
            "started": started,
            "failed": failed,
            "config_params": [],
            "config_values": {},
            "tools": [],
        }

        if isinstance(svc, Configurable):
            entry["config_namespace"] = svc.config_namespace
            entry["config_params"] = [
                {
                    "key": p.key,
                    "type": p.type.value,
                    "description": p.description,
                    "default": p.default,
                    "restart_required": p.restart_required,
                }
                for p in svc.config_params()
            ]
            if isinstance(config_svc, ConfigurationService):
                entry["config_values"] = config_svc.get_section(svc.config_namespace)

        if isinstance(svc, ToolProvider):
            entry["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "required_role": t.required_role,
                    "parameters": [
                        {"name": p.name, "type": p.type.value, "description": p.description, "required": p.required}
                        for p in t.parameters
                    ],
                }
                for t in svc.get_tools()
            ]

        services.append(entry)

    return {"services": services}
