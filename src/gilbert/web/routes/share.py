"""Public share-token download endpoint.

``share_workspace_file`` (AI tool in ``WorkspaceService``) mints a token
pointing at a specific workspace file. External consumers (speakers,
SMS/MMS bridges, anything that needs a URL rather than a local path)
fetch the file through this endpoint — the token *is* the auth, so the
route intentionally bypasses Gilbert's session auth.

The actual token lookup + access-count enforcement lives on
``WorkspaceService.consume_file_share``; this module is just the HTTP
adapter that turns a resolved file path into a ``FileResponse``.

We use ``FileResponse`` rather than ``StreamingResponse`` on purpose:
UPnP / DLNA consumers (Sonos especially) parse the HTTP response
headers before starting playback and require a concrete
``Content-Length`` and working Range support to build DIDL-Lite
metadata. ``StreamingResponse`` uses chunked transfer encoding with no
Content-Length, which Sonos rejects with UPnP error 714 / 716 on some
firmware generations.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/share")


@router.get("/{token}")
async def download_share(token: str, request: Request) -> FileResponse:
    """Serve the file referenced by ``token``.

    404s when the token is unknown, expired, exhausted, or the underlying
    file is missing. Does not differentiate the reasons — leaking
    "exists but exhausted" would help an attacker enumerate valid tokens.
    """
    workspace_svc = _resolve_workspace_service(request)
    resolved = await workspace_svc.consume_file_share(token)
    if resolved is None:
        raise HTTPException(status_code=404)

    file_path, media_type, _filename = resolved
    # FileResponse handles Content-Length, Range requests, and efficient
    # zero-copy sendfile on Linux — exactly what picky UPnP devices need.
    # ``no-store`` prevents caching a URL that may get revoked when its
    # access counter runs out.
    return FileResponse(
        path=file_path,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


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
