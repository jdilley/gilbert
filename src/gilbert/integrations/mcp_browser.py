"""MCP backend that proxies through a user's WebSocket to their browser.

The owning user's browser runs a thin bridge that forwards JSON-RPC
bodies to an MCP server running on its own localhost (or any URL the
browser can reach). This backend turns each ``list_tools`` /
``call_tool`` into an ``mcp.bridge.call`` frame sent over the user's
already-authenticated WebSocket via the outbound-RPC primitive, awaits
the reply, and unwraps the JSON-RPC result into the existing MCP types.

Unlike the stdio / http backends, this one is **never** driven by
``MCPService._supervise`` — browser entries are ephemeral, bound 1:1
to a live WS session, and torn down when that session closes. The
backend is created, ``bind()``-ed to a connection, and given a record
that was constructed in memory by the announce handler.

Because the browser is a transport proxy and nothing more, the JSON
shapes on the wire mirror MCP's own schema exactly: ``inputSchema``
instead of Pythonified ``input_schema``, ``isError`` instead of
``is_error``, etc. The backend accepts both spellings defensively so
a helper bridge that happens to rename fields still works.
"""

from __future__ import annotations

from typing import Any, cast

from gilbert.interfaces.mcp import (
    MCPBackend,
    MCPContentBlock,
    MCPServerRecord,
    MCPToolResult,
    MCPToolSpec,
)
from gilbert.interfaces.ws import WsConnectionBase


class BrowserMCPBackend(MCPBackend):
    """MCP backend that rides the owning user's WebSocket.

    Construction is two-step: ``MCPBackend.registered_backends()`` returns
    the class, the service instantiates it, then calls ``bind()`` with
    the live connection and slug before ``connect()``. Any call on an
    un-bound or closed backend raises ``ConnectionError`` so the session
    registry can surface a clean error to the caller.
    """

    backend_name = "browser"

    def __init__(self) -> None:
        self._conn: WsConnectionBase | None = None
        self._slug: str = ""
        self._call_timeout: float = 30.0

    def bind(
        self,
        conn: WsConnectionBase,
        slug: str,
        *,
        call_timeout: float = 30.0,
    ) -> None:
        """Attach to a live WS connection. Called by MCPService before
        ``connect`` when wiring up a session entry."""
        self._conn = conn
        self._slug = slug
        self._call_timeout = call_timeout

    async def connect(self, record: MCPServerRecord) -> None:
        """Verify that a connection has been bound.

        Browser backends have no handshake of their own — the WS is
        already open when we get here, and a ``tools/list`` probe
        right after ``connect`` (driven by the caller) is what
        actually validates that the browser side can reach the
        underlying MCP server.
        """
        if self._conn is None:
            raise ConnectionError(
                f"BrowserMCPBackend {self._slug!r} not bound to a WS connection",
            )

    async def close(self) -> None:
        self._conn = None

    async def list_tools(self) -> list[MCPToolSpec]:
        result = await self._call_bridge("tools/list", {})
        tools_raw = result.get("tools") or []
        out: list[MCPToolSpec] = []
        for item in tools_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            schema = item.get("inputSchema") or item.get("input_schema") or {}
            if not isinstance(schema, dict):
                schema = {}
            out.append(
                MCPToolSpec(
                    name=name,
                    description=str(item.get("description") or ""),
                    input_schema=dict(schema),
                )
            )
        return out

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        result = await self._call_bridge(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        content_raw = result.get("content") or []
        blocks: list[MCPContentBlock] = []
        for item in content_raw:
            if not isinstance(item, dict):
                continue
            kind_raw = str(item.get("type") or "text")
            if kind_raw not in ("text", "image", "resource", "audio"):
                kind_raw = "text"
            blocks.append(
                MCPContentBlock(
                    type=cast(Any, kind_raw),
                    text=str(item.get("text") or ""),
                    data=str(item.get("data") or ""),
                    mime_type=str(
                        item.get("mimeType") or item.get("mime_type") or ""
                    ),
                    uri=str(item.get("uri") or ""),
                )
            )
        structured = result.get("structuredContent") or result.get("structured")
        return MCPToolResult(
            content=tuple(blocks),
            is_error=bool(result.get("isError") or result.get("is_error")),
            structured=structured if isinstance(structured, dict) else None,
        )

    async def _call_bridge(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a bridge frame and return the unwrapped MCP ``result``.

        The browser bridge wraps its reply in
        ``{ok: true, result: <mcp-result>}`` on success or
        ``{ok: false, error: "..."}`` on failure. We translate the
        failure case into a ``RuntimeError`` so the service layer's
        existing error handling (timeouts, caller messaging) applies
        uniformly across transports.
        """
        conn = self._conn
        if conn is None:
            raise ConnectionError(
                f"Browser MCP server {self._slug!r} is not connected",
            )
        frame = {
            "type": "mcp.bridge.call",
            "server": self._slug,
            "method": method,
            "params": params,
        }
        reply = await conn.call_client(frame, timeout=self._call_timeout)
        if not reply.get("ok", False):
            err = str(reply.get("error") or "browser bridge call failed")
            raise RuntimeError(f"Browser MCP {self._slug!r} {method}: {err}")
        result = reply.get("result")
        if not isinstance(result, dict):
            return {}
        return result
