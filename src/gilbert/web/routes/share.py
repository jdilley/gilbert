"""Public share-token download endpoint.

``share_workspace_file`` (AI tool in ``WorkspaceService``) mints a token
pointing at a specific workspace file. External consumers (speakers,
SMS/MMS bridges, anything that needs a URL rather than a local path)
fetch the file through this endpoint — the token *is* the auth, so the
route intentionally bypasses Gilbert's session auth.

The actual token lookup + access-count enforcement lives on
``WorkspaceService.consume_file_share``; this module is just the HTTP
adapter that turns a resolved file path into a streamed response.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/share")

_STREAM_CHUNK = 64 * 1024  # 64 KiB — balances syscalls vs memory


@router.get("/{token}")
async def download_share(token: str, request: Request) -> StreamingResponse:
    """Stream the file referenced by ``token``.

    404s when the token is unknown, expired, exhausted, or the underlying
    file is missing. Does not differentiate the reasons — leaking
    "exists but exhausted" would help an attacker enumerate valid tokens.
    """
    workspace_svc = _resolve_workspace_service(request)
    resolved = await workspace_svc.consume_file_share(token)
    if resolved is None:
        raise HTTPException(status_code=404)

    file_path, media_type, filename = resolved

    async def _stream() -> Any:
        # Read in chunks so even multi-hundred-MB files don't balloon
        # the process RSS. StreamingResponse handles back-pressure via
        # the client's read rate.
        def _reader() -> Any:
            with file_path.open("rb") as fh:
                while True:
                    chunk = fh.read(_STREAM_CHUNK)
                    if not chunk:
                        return
                    yield chunk

        # StreamingResponse wants an iterator, not a generator-returning
        # callable; materialise it here.
        for chunk in _reader():
            yield chunk

    # ``inline`` disposition lets browsers preview audio/images without
    # forcing a download, while still giving HTTP clients a filename hint.
    # Sonos and similar media consumers ignore the header either way.
    safe_name = Path(filename).name or "file"
    headers = {
        "Content-Disposition": f'inline; filename="{safe_name}"',
        "Cache-Control": "no-store",
    }
    return StreamingResponse(_stream(), media_type=media_type, headers=headers)


def _resolve_workspace_service(request: Request) -> Any:
    """Pull the WorkspaceService off the running Gilbert instance.

    503 when no workspace service is live — either the app is still
    booting or the service failed to start."""
    gilbert = getattr(request.app.state, "gilbert", None)
    if gilbert is None:
        raise HTTPException(status_code=503)
    svc = gilbert.service_manager.get_by_capability("workspace")
    if svc is None:
        raise HTTPException(status_code=503)
    return svc
