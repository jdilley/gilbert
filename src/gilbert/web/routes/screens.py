"""Screen display routes — setup page, SSE push, temp file serving, and API.

Routes:
- ``GET /screens``              — renders the screen setup/display page
- ``GET /screens/stream``       — SSE endpoint (requires ``?name=`` query param)
- ``GET /screens/api``          — list connected screens as JSON
- ``GET /screens/tmp/{token}``  — serve a temp file (PDF or image) by token
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from gilbert.interfaces.auth import UserContext
from gilbert.web.auth import require_role

router = APIRouter(prefix="/screens")


def _get_screen_service(request: Request) -> Any:
    """Get the ScreenService from the app, or raise 503."""
    gilbert = request.app.state.gilbert
    svc = gilbert.service_manager.get_by_capability("screen_display")
    if svc is None:
        raise HTTPException(status_code=503, detail="Screen service not available")
    return svc


@router.get("/stream", response_model=None)
async def screens_stream(
    request: Request,
    name: str = Query(..., min_length=1),
    default_url: str | None = Query(None),
) -> StreamingResponse:
    """SSE endpoint — browser connects here to receive push events."""
    screen_svc = _get_screen_service(request)
    screen = screen_svc.connect(name, default_url=default_url)
    return StreamingResponse(
        screen_svc.event_stream(screen),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api")
async def screens_api(
    request: Request,
    user: UserContext = Depends(require_role("user")),
) -> JSONResponse:
    """List all connected screens."""
    screen_svc = _get_screen_service(request)
    return JSONResponse(content={"screens": screen_svc.list_screens()})


@router.get("/tmp/{token}", response_model=None)
async def screen_tmp_file(
    request: Request,
    token: str,
) -> FileResponse:
    """Serve a temporary file (PDF or image) by token."""
    screen_svc = _get_screen_service(request)
    path = screen_svc.get_temp_path(token)
    if not path:
        raise HTTPException(status_code=404, detail="File not found or expired")

    media_type = screen_svc.get_temp_mime_type(token)
    return FileResponse(path, media_type=media_type)
