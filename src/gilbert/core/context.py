"""Request context — async-safe current-user propagation."""

from contextvars import ContextVar

from gilbert.interfaces.auth import UserContext

_current_user: ContextVar[UserContext] = ContextVar("_current_user")


def get_current_user() -> UserContext:
    """Return the current user, or ``UserContext.SYSTEM`` if none is set."""
    return _current_user.get(UserContext.SYSTEM)


def set_current_user(user: UserContext) -> None:
    """Set the current user for the running async context."""
    _current_user.set(user)
