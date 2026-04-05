"""Document browser routes — browse, search, and serve documents."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse

from gilbert.core.app import Gilbert
from gilbert.interfaces.auth import UserContext
from gilbert.web import templates
from gilbert.web.auth import require_role

router = APIRouter(prefix="/documents")


def _get_knowledge(gilbert: Gilbert) -> Any:
    svc = gilbert.service_manager.get_by_capability("knowledge")
    if svc is None:
        raise HTTPException(status_code=503, detail="Knowledge service not available")
    return svc


def _build_tree(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a nested folder tree from flat document list."""
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


def _count_files(node: dict[str, Any]) -> int:
    """Count total files in a tree node recursively."""
    count = len(node.get("_files", []))
    for sub in node.get("_folders", {}).values():
        count += _count_files(sub)
    return count


@router.get("")
async def document_browser(
    request: Request,
    user: UserContext = Depends(require_role("user")),
) -> Any:
    """Browse all documents in an expandable tree view."""
    gilbert: Gilbert = request.app.state.gilbert
    knowledge = _get_knowledge(gilbert)

    # Get entity storage for tracking info
    storage = None
    storage_svc = gilbert.service_manager.get_by_capability("entity_storage")
    if storage_svc is not None:
        storage = getattr(storage_svc, "backend", None)

    # Bulk-load all tracking data from entity store
    tracking_map: dict[str, dict[str, Any]] = {}
    if storage:
        try:
            from gilbert.interfaces.storage import Query
            all_tracking = await storage.query(Query(collection="knowledge_documents"))
            for t in all_tracking:
                tracking_map[t.get("document_id", "")] = t
        except Exception:
            pass

    # Build a tree per source using cached file lists from the backends.
    # The backends cache their file lists from the last sync, so this
    # should be fast (no API calls).
    source_trees: list[dict[str, Any]] = []
    for backend in knowledge.backends.values():
        # Use tracking data to build the tree instead of re-listing from the backend
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
            # Fall back to listing from backend if no tracking data yet
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

        tree = _build_tree(all_docs)
        source_trees.append({
            "source_id": backend.source_id,
            "display_name": backend.display_name,
            "tree": tree,
            "file_count": _count_files(tree),
        })

    return templates.TemplateResponse(request, "documents.html", {
        "source_trees": source_trees,
        "user": user,
    })


@router.get("/search")
async def document_search(
    request: Request,
    q: str = "",
    source: str | None = None,
    user: UserContext = Depends(require_role("user")),
) -> Any:
    """Search documents."""
    gilbert: Gilbert = request.app.state.gilbert
    knowledge = _get_knowledge(gilbert)

    results: list[dict[str, Any]] = []
    if q:
        # Bulk-load tracking data for URL resolution
        tracking_map: dict[str, dict[str, Any]] = {}
        storage_svc = gilbert.service_manager.get_by_capability("entity_storage")
        if storage_svc is not None:
            storage = getattr(storage_svc, "backend", None)
            if storage:
                try:
                    from gilbert.interfaces.storage import Query as SQuery
                    all_tracking = await storage.query(SQuery(collection="knowledge_documents"))
                    tracking_map = {t.get("document_id", ""): t for t in all_tracking}
                except Exception:
                    pass

        response = await knowledge.search(q, n_results=10, source_filter=source)
        for r in response.results:
            tracking = tracking_map.get(r.document_id, {})
            external_url = tracking.get("external_url", "")
            url = external_url or f"/documents/serve/{r.source_id}/{r.path}"
            results.append({
                "document_id": r.document_id,
                "name": r.name,
                "source_id": r.source_id,
                "relevance": f"{r.relevance_score:.1%}",
                "text": r.chunk_text[:300] + ("..." if len(r.chunk_text) > 300 else ""),
                "page": r.page_number,
                "type": r.document_type.value,
                "url": url,
                "external": bool(external_url),
            })

    return templates.TemplateResponse(request, "document_search.html", {
        "query": q,
        "results": results,
        "user": user,
    })


@router.get("/serve/{full_path:path}")
async def serve_document(
    request: Request,
    full_path: str,
    user: UserContext = Depends(require_role("user")),
) -> StreamingResponse:
    """Serve a document file from any backend.

    The full_path is source_id:document_path (e.g., 'gdrive:library/folder/file.pdf'
    or 'local:docs/report.pdf'). We match against known source_ids to split it.
    """
    gilbert: Gilbert = request.app.state.gilbert
    knowledge = _get_knowledge(gilbert)

    # Find the matching backend by trying each source_id as a prefix
    backend = None
    document_path = ""
    for sid in knowledge.backends:
        prefix = sid + "/"
        if full_path.startswith(prefix):
            backend = knowledge.get_backend(sid)
            document_path = full_path[len(prefix):]
            break

    if backend is None:
        raise HTTPException(status_code=404, detail=f"Source not found in path: {full_path}")

    meta = await backend.get_metadata(document_path)
    if meta is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return StreamingResponse(
        backend.stream_document(document_path),
        media_type=meta.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{meta.name}"'},
    )
