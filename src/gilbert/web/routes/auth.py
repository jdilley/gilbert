"""Auth routes — login, logout, current-user info, provider sync."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from gilbert.core.app import Gilbert
from gilbert.interfaces.auth import UserContext
from gilbert.web.auth import get_user_context, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_require_admin: Any = Depends(require_role("admin"))


def _get_auth_service(request: Request) -> Any:
    gilbert: Gilbert = request.app.state.gilbert
    svc = gilbert.service_manager.get_by_capability("authentication")
    if svc is None:
        raise HTTPException(status_code=503, detail="Authentication is not enabled")
    return svc


@router.post("/login")
async def login(request: Request, response: Response) -> dict:
    """Authenticate and create a session.

    Expects JSON body: ``{"provider": "local", "email": "...", "password": "..."}``.
    Provider-specific fields vary.
    """
    auth_svc = _get_auth_service(request)
    body = await request.json()

    provider_type = body.pop("provider", "local")
    user_ctx = await auth_svc.authenticate(provider_type, body)
    if user_ctx is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Set session cookie.
    if user_ctx.session_id:
        response.set_cookie(
            key="gilbert_session",
            value=user_ctx.session_id,
            httponly=True,
            samesite="lax",
        )

    return {
        "user_id": user_ctx.user_id,
        "email": user_ctx.email,
        "display_name": user_ctx.display_name,
        "roles": sorted(user_ctx.roles),
        "session_id": user_ctx.session_id,
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    user: UserContext = Depends(get_user_context),  # noqa: B008
) -> dict:
    """Invalidate the current session."""
    if user.session_id:
        auth_svc = _get_auth_service(request)
        await auth_svc.invalidate_session(user.session_id)
    response.delete_cookie("gilbert_session")
    return {"status": "ok"}


@router.get("/me")
async def me(user: UserContext = Depends(get_user_context)) -> dict:  # noqa: B008
    """Return the current user's identity."""
    return {
        "user_id": user.user_id,
        "email": user.email,
        "display_name": user.display_name,
        "roles": sorted(user.roles),
        "provider": user.provider,
    }


@router.post("/sync/{provider_type}")
async def sync_provider(
    request: Request,
    provider_type: str,
    _user: UserContext = _require_admin,
) -> dict:
    """Trigger a user sync from an external provider (admin only)."""
    auth_svc = _get_auth_service(request)
    try:
        count = await auth_svc.sync_provider(provider_type)
    except KeyError as err:
        raise HTTPException(
            status_code=404, detail=f"Unknown provider: {provider_type}"
        ) from err
    return {"status": "ok", "synced": count}
