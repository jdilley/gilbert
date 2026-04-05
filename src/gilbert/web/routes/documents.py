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


@router.get("")
async def document_browser(
    request: Request,
    source: str | None = None,
    user: UserContext = Depends(require_role("user")),
) -> Any:
    """Browse documents by source."""
    gilbert: Gilbert = request.app.state.gilbert
    knowledge = _get_knowledge(gilbert)

    sources = [
        {"source_id": b.source_id, "display_name": b.display_name, "read_only": b.read_only}
        for b in knowledge.backends.values()
    ]

    documents: list[dict[str, Any]] = []
    target_backends = (
        [knowledge.get_backend(source)] if source else list(knowledge.backends.values())
    )
    for backend in target_backends:
        if backend is None:
            continue
        try:
            docs = await backend.list_documents()
            for d in docs:
                documents.append({
                    "document_id": d.document_id,
                    "name": d.name,
                    "source_id": d.source_id,
                    "type": d.document_type.value,
                    "size": d.size_bytes,
                    "modified": d.last_modified,
                    "serve_url": f"/documents/serve/{d.source_id}/{d.path}",
                })
        except Exception:
            pass

    return templates.TemplateResponse(request, "documents.html", {
        "sources": sources,
        "documents": documents,
        "current_source": source,
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
        response = await knowledge.search(q, n_results=10, source_filter=source)
        for r in response.results:
            results.append({
                "document_id": r.document_id,
                "name": r.name,
                "source_id": r.source_id,
                "relevance": f"{r.relevance_score:.1%}",
                "text": r.chunk_text[:300] + ("..." if len(r.chunk_text) > 300 else ""),
                "page": r.page_number,
                "type": r.document_type.value,
                "serve_url": f"/documents/serve/{r.source_id}/{r.path}",
            })

    return templates.TemplateResponse(request, "document_search.html", {
        "query": q,
        "results": results,
        "user": user,
    })


@router.get("/serve/{source_id:path}/{document_path:path}")
async def serve_document(
    request: Request,
    source_id: str,
    document_path: str,
    user: UserContext = Depends(require_role("user")),
) -> StreamingResponse:
    """Serve a document file from any backend."""
    gilbert: Gilbert = request.app.state.gilbert
    knowledge = _get_knowledge(gilbert)

    backend = knowledge.get_backend(source_id)
    if backend is None:
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")

    meta = await backend.get_metadata(document_path)
    if meta is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return StreamingResponse(
        backend.stream_document(document_path),
        media_type=meta.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{meta.name}"'},
    )
