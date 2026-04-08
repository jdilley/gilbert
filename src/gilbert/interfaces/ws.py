"""WebSocket handler provider interface.

Services implement this protocol to register WS RPC frame handlers,
similar to how ``ToolProvider`` exposes AI tools. Declare the
``ws_handlers`` capability in ``ServiceInfo`` to be discovered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from gilbert.web.ws_protocol import RpcHandler


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
