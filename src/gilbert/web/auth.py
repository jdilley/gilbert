"""Web authentication — middleware and FastAPI dependencies."""

from typing import Any

from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import RedirectResponse, Response

from gilbert.core.context import set_current_user
from gilbert.interfaces.auth import UserContext

# Paths that bypass authentication.
# Exact matches checked first, then prefixes.
_PUBLIC_EXACT = ("/auth/login", "/auth/session")
_PUBLIC_PREFIXES = ("/auth/login/", "/static/", "/output/")


class AuthMiddleware(BaseHTTPMiddleware):
    """Sets the current user on every request.

    Checks for a ``gilbert_session`` cookie or ``Authorization: Bearer``
    header.  If the auth service is not running (auth disabled), all
    requests proceed as ``UserContext.SYSTEM``.

    Unauthenticated requests to non-public paths are redirected to the
    login page.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        user = UserContext.SYSTEM

        gilbert = getattr(request.app.state, "gilbert", None)
        auth_enabled = False
        if gilbert is not None:
            auth_svc = gilbert.service_manager.get_by_capability("authentication")
            if auth_svc is not None:
                auth_enabled = True
                session_id = _extract_session(request)
                if session_id:
                    ctx = await auth_svc.validate_session(session_id)
                    if ctx is not None:
                        user = ctx

        request.state.user = user
        set_current_user(user)

        # Redirect unauthenticated users to login (skip public paths).
        is_public = path in _PUBLIC_EXACT or any(
            path.startswith(p) for p in _PUBLIC_PREFIXES
        )
        if auth_enabled and not is_public and user.user_id == "system":
            return RedirectResponse(url="/auth/login", status_code=302)

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
    """Factory returning a dependency that checks for a role using the hierarchy.

    Uses AccessControlService if available, otherwise falls back to a
    hardcoded built-in hierarchy.
    """
    # Fallback hierarchy when AccessControlService is unavailable
    _BUILTIN_LEVELS = {"admin": 0, "user": 100, "everyone": 200}

    async def _check(
        request: Request,
        user: UserContext = Depends(require_authenticated),  # noqa: B008
    ) -> UserContext:
        gilbert = getattr(request.app.state, "gilbert", None)
        if gilbert is not None:
            acl_svc = gilbert.service_manager.get_by_capability("access_control")
            if acl_svc is not None:
                required_level = acl_svc.get_role_level(role)
                effective_level = acl_svc.get_effective_level(user)
                if effective_level <= required_level:
                    return user
                raise HTTPException(status_code=403, detail=f"Requires role: {role}")

        # Fallback: hardcoded levels
        required_level = _BUILTIN_LEVELS.get(role, 100)
        user_level = min((_BUILTIN_LEVELS.get(r, 100) for r in user.roles), default=200)
        if user_level <= required_level:
            return user
        raise HTTPException(status_code=403, detail=f"Requires role: {role}")

    return _check
