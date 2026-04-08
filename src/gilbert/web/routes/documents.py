"""Document browser routes — browse, search, and serve documents."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse

from gilbert.core.app import Gilbert
from gilbert.interfaces.auth import UserContext
from gilbert.web.auth import require_role

router = APIRouter(prefix="/documents")


def _get_knowledge(gilbert: Gilbert) -> Any:
    svc = gilbert.service_manager.get_by_capability("knowledge")
    if svc is None:
        raise HTTPException(status_code=503, detail="Knowledge service not available")
    return svc


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
