"""WebSocket handler provider interface.

Services implement this protocol to register WS RPC frame handlers,
similar to how ``ToolProvider`` exposes AI tools. Declare the
``ws_handlers`` capability in ``ServiceInfo`` to be discovered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from gilbert.web.ws_protocol import RpcHandler, WsConnection


@runtime_checkable
class WsHandlerProvider(Protocol):
    """Protocol for services that expose WebSocket RPC handlers."""

    def get_ws_handlers(self) -> dict[str, "RpcHandler"]:
        """Return a mapping of frame type → async handler function.

        Each handler receives ``(conn: WsConnection, frame: dict)`` and
        returns an optional response dict (or None for no response).

        Frame types use ``namespace.resource.verb`` naming, e.g.
        ``chat.message.send``, ``roles.role.create``.
        """
        ...


def require_admin(conn: "WsConnection", frame: dict[str, Any]) -> dict[str, Any] | None:
    """Return an error frame if the connection is not admin-level, else None.

    Shared helper for WS handlers that require admin access.
    """
    if conn.user_level > 0:
        return {"type": "gilbert.error", "ref": frame.get("id"), "error": "Admin access required", "code": 403}
    return None
