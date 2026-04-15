"""Stdio transport for MCP client connections.

Implements ``MCPBackend`` for servers that speak MCP over a subprocess's
stdin/stdout. Uses the official ``mcp`` SDK's ``stdio_client`` +
``ClientSession`` context managers, kept alive across the backend's
``connect()``/``close()`` lifecycle via an ``AsyncExitStack``.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp import types as mcp_types
from mcp.client.stdio import stdio_client
from mcp.shared.session import RequestResponder
from pydantic import AnyUrl

from gilbert.interfaces.mcp import (
    MCPBackend,
    MCPContentBlock,
    MCPPromptArgument,
    MCPPromptMessage,
    MCPPromptResult,
    MCPPromptSpec,
    MCPResourceContent,
    MCPResourceSpec,
    MCPServerRecord,
    MCPToolResult,
    MCPToolSpec,
)

logger = logging.getLogger(__name__)


class StdioMCPBackend(MCPBackend):
    """MCP backend that talks to a subprocess over stdin/stdout."""

    backend_name = "stdio"

    def __init__(self) -> None:
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None
        self._tools_changed_cb: Any = None
        self._sampling_cb: Any = None
        self._record: MCPServerRecord | None = None

    async def connect(self, record: MCPServerRecord) -> None:
        if self._session is not None:
            raise RuntimeError("StdioMCPBackend already connected")
        if not record.command:
            raise ValueError("MCP server record has no command")

        params = StdioServerParameters(
            command=record.command[0],
            args=list(record.command[1:]),
            env=dict(record.env) if record.env else None,
            cwd=record.cwd,
        )

        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(
                ClientSession(
                    read,
                    write,
                    message_handler=self._handle_message,
                    sampling_callback=self._sampling_cb,
                )
            )
            await session.initialize()
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        self._record = record

    async def close(self) -> None:
        self._session = None
        self._record = None
        stack, self._stack = self._stack, None
        if stack is not None:
            try:
                await stack.aclose()
            except Exception as exc:  # pragma: no cover - best-effort cleanup
                logger.warning("Error closing stdio MCP backend: %s", exc)

    async def list_tools(self) -> list[MCPToolSpec]:
        session = self._require_session()
        result = await session.list_tools()
        specs: list[MCPToolSpec] = []
        for tool in result.tools:
            specs.append(
                MCPToolSpec(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=dict(tool.inputSchema) if tool.inputSchema else {},
                )
            )
        return specs

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        session = self._require_session()
        result = await session.call_tool(name, arguments)
        content = tuple(self._translate_block(block) for block in result.content)
        structured = getattr(result, "structuredContent", None)
        return MCPToolResult(
            content=content,
            is_error=bool(result.isError),
            structured=dict(structured) if isinstance(structured, dict) else None,
        )

    async def list_resources(self) -> list[MCPResourceSpec]:
        session = self._require_session()
        result = await session.list_resources()
        specs: list[MCPResourceSpec] = []
        for resource in result.resources:
            specs.append(
                MCPResourceSpec(
                    uri=str(resource.uri),
                    name=resource.name or "",
                    description=resource.description or "",
                    mime_type=resource.mimeType or "",
                    size=resource.size,
                )
            )
        return specs

    async def read_resource(self, uri: str) -> list[MCPResourceContent]:
        session = self._require_session()
        result = await session.read_resource(AnyUrl(uri))
        return [_translate_resource_content(c) for c in result.contents]

    async def list_prompts(self) -> list[MCPPromptSpec]:
        session = self._require_session()
        result = await session.list_prompts()
        return [_translate_prompt_spec(p) for p in result.prompts]

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str],
    ) -> MCPPromptResult:
        session = self._require_session()
        result = await session.get_prompt(name, arguments or None)
        return _translate_prompt_result(result)

    async def set_tools_changed_callback(self, callback: Any) -> None:
        self._tools_changed_cb = callback

    async def set_sampling_callback(self, callback: Any) -> None:
        self._sampling_cb = callback

    # ── internals ────────────────────────────────────────────────────

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("StdioMCPBackend is not connected")
        return self._session

    async def _handle_message(
        self,
        message: (
            RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult]
            | mcp_types.ServerNotification
            | Exception
        ),
    ) -> None:
        """Route server-initiated messages.

        Part 1 only handles the ``tools/list_changed`` notification; other
        notifications (logging, progress, resource updates) are ignored
        until later parts wire them through."""
        if isinstance(message, Exception):
            logger.debug("MCP transport error for %s: %s", self._server_label(), message)
            return
        if isinstance(message, mcp_types.ServerNotification):
            root = message.root
            if isinstance(root, mcp_types.ToolListChangedNotification):
                cb = self._tools_changed_cb
                if cb is not None:
                    try:
                        await cb()
                    except Exception:
                        logger.exception(
                            "tools/list_changed callback failed for %s",
                            self._server_label(),
                        )

    def _translate_block(self, block: Any) -> MCPContentBlock:
        """Translate an MCP content block into Gilbert's flat dataclass.

        The SDK uses a discriminated union (``TextContent`` / ``ImageContent``
        / ``AudioContent`` / ``EmbeddedResource``). Part 1 flattens them so
        downstream code can pattern-match on ``block.type`` without importing
        SDK types."""
        kind = getattr(block, "type", "")
        if kind == "text":
            return MCPContentBlock(type="text", text=getattr(block, "text", "") or "")
        if kind == "image":
            return MCPContentBlock(
                type="image",
                data=getattr(block, "data", "") or "",
                mime_type=getattr(block, "mimeType", "") or "",
            )
        if kind == "audio":
            return MCPContentBlock(
                type="audio",
                data=getattr(block, "data", "") or "",
                mime_type=getattr(block, "mimeType", "") or "",
            )
        if kind == "resource":
            resource = getattr(block, "resource", None)
            uri = getattr(resource, "uri", "") if resource is not None else ""
            text = getattr(resource, "text", "") if resource is not None else ""
            mime = getattr(resource, "mimeType", "") if resource is not None else ""
            return MCPContentBlock(
                type="resource",
                text=text or "",
                uri=str(uri) if uri else "",
                mime_type=mime or "",
            )
        # Unknown block type — stringify so nothing is silently dropped.
        return MCPContentBlock(type="text", text=str(block))

    def _server_label(self) -> str:
        if self._record is None:
            return "<unknown>"
        return f"{self._record.name} ({self._record.id})"


def _translate_prompt_spec(prompt: Any) -> MCPPromptSpec:
    """Translate an SDK ``Prompt`` into Gilbert's ``MCPPromptSpec``."""
    args_raw = getattr(prompt, "arguments", None) or []
    arguments = tuple(
        MCPPromptArgument(
            name=str(getattr(a, "name", "") or ""),
            description=str(getattr(a, "description", "") or ""),
            required=bool(getattr(a, "required", False)),
        )
        for a in args_raw
    )
    return MCPPromptSpec(
        name=str(getattr(prompt, "name", "") or ""),
        title=str(getattr(prompt, "title", "") or ""),
        description=str(getattr(prompt, "description", "") or ""),
        arguments=arguments,
    )


def _translate_prompt_result(result: Any) -> MCPPromptResult:
    """Translate an SDK ``GetPromptResult`` into Gilbert's dataclass.

    Each ``PromptMessage`` becomes an ``MCPPromptMessage`` with the
    original role and a single ``MCPContentBlock`` for the content.
    ``PromptMessage.content`` is always a single content block in the
    current SDK."""
    messages_raw = getattr(result, "messages", None) or []
    messages: list[MCPPromptMessage] = []
    for m in messages_raw:
        role_raw = getattr(m, "role", "user") or "user"
        role: Any = role_raw if role_raw in ("user", "assistant", "system") else "user"
        content = getattr(m, "content", None)
        if content is None:
            block = MCPContentBlock(type="text", text="")
        else:
            # Reuse the tool-call block translator; content shapes are
            # compatible (TextContent, ImageContent, ResourceContent,
            # AudioContent — same discriminated union).
            block = _stdio_block_from_sdk(content)
        messages.append(MCPPromptMessage(role=role, content=block))
    return MCPPromptResult(
        description=str(getattr(result, "description", "") or ""),
        messages=tuple(messages),
    )


def _stdio_block_from_sdk(block: Any) -> MCPContentBlock:
    """Delegate to ``StdioMCPBackend._translate_block`` — this helper
    exists so ``_translate_prompt_result`` doesn't need access to the
    backend instance (prompts are typed at module scope)."""
    kind = getattr(block, "type", "")
    if kind == "text":
        return MCPContentBlock(type="text", text=getattr(block, "text", "") or "")
    if kind == "image":
        return MCPContentBlock(
            type="image",
            data=getattr(block, "data", "") or "",
            mime_type=getattr(block, "mimeType", "") or "",
        )
    if kind == "audio":
        return MCPContentBlock(
            type="audio",
            data=getattr(block, "data", "") or "",
            mime_type=getattr(block, "mimeType", "") or "",
        )
    if kind == "resource":
        resource = getattr(block, "resource", None)
        uri = getattr(resource, "uri", "") if resource is not None else ""
        text = getattr(resource, "text", "") if resource is not None else ""
        mime = getattr(resource, "mimeType", "") if resource is not None else ""
        return MCPContentBlock(
            type="resource",
            text=text or "",
            uri=str(uri) if uri else "",
            mime_type=mime or "",
        )
    return MCPContentBlock(type="text", text=str(block))


def _translate_resource_content(content: Any) -> MCPResourceContent:
    """Flatten the SDK's ``TextResourceContents`` / ``BlobResourceContents``
    discriminated union into Gilbert's single dataclass."""
    uri = str(getattr(content, "uri", "") or "")
    mime = str(getattr(content, "mimeType", "") or "")
    text = getattr(content, "text", None)
    if text is not None:
        return MCPResourceContent(
            uri=uri,
            kind="text",
            mime_type=mime,
            text=str(text),
        )
    blob = getattr(content, "blob", None)
    if blob is not None:
        return MCPResourceContent(
            uri=uri,
            kind="blob",
            mime_type=mime,
            data=str(blob),
        )
    # Neither shape matched — surface as empty text so the UI gets a
    # deterministic fallback rather than a crash.
    return MCPResourceContent(uri=uri, kind="text", mime_type=mime)
