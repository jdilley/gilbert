"""Web authentication — middleware and FastAPI dependencies."""

from typing import Any

from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from gilbert.core.context import set_current_user
from gilbert.interfaces.auth import UserContext


class AuthMiddleware(BaseHTTPMiddleware):
    """Sets the current user on every request.

    Checks for a ``gilbert_session`` cookie or ``Authorization: Bearer``
    header.  If the auth service is not running (auth disabled), all
    requests proceed as ``UserContext.SYSTEM``.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        user = UserContext.SYSTEM

        gilbert = getattr(request.app.state, "gilbert", None)
        if gilbert is not None:
            auth_svc = gilbert.service_manager.get_by_capability("authentication")
            if auth_svc is not None:
                session_id = _extract_session(request)
                if session_id:
                    ctx = await auth_svc.validate_session(session_id)
                    if ctx is not None:
                        user = ctx

        request.state.user = user
        set_current_user(user)

        return await call_next(request)


def _extract_session(request: Request) -> str | None:
    """Pull a session token from cookie or Authorization header."""
    # Cookie first.
    session_id = request.cookies.get("gilbert_session")
    if session_id:
        return session_id

    # Bearer token fallback.
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    return None


# ---- FastAPI dependencies ----


async def get_user_context(request: Request) -> UserContext:
    """Dependency that returns the current user (may be SYSTEM)."""
    return getattr(request.state, "user", UserContext.SYSTEM)


async def require_authenticated(request: Request) -> UserContext:
    """Dependency that requires a logged-in user (raises 401)."""
    user: UserContext = getattr(request.state, "user", UserContext.SYSTEM)
    if user.user_id == "system":
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_role(role: str) -> Any:
    """Factory returning a dependency that checks for a specific role."""

    async def _check(
        user: UserContext = Depends(require_authenticated),  # noqa: B008
    ) -> UserContext:
        if role not in user.roles:
            raise HTTPException(
                status_code=403, detail=f"Requires role: {role}"
            )
        return user

    return _check
