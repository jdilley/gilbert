"""Remote-transport MCP backends — Streamable HTTP and SSE.

Both speak MCP over HTTP to an external URL. Unlike the stdio backend
(which uses an ``AsyncExitStack`` to keep the transport context manager
alive across imperative ``connect``/``close`` calls), the HTTP and SSE
transports spawn internal anyio task groups during ``__aenter__`` that
MUST be cleaned up by the same task that entered them — otherwise
anyio raises ``Attempted to exit cancel scope in a different task``.

To satisfy that constraint without throwing out Gilbert's imperative
``MCPBackend`` ABC, the shared base runs the session inside a
dedicated asyncio task (``_session_task``). The task opens the
transport and ``ClientSession`` inside a normal ``async with`` block
— guaranteeing that teardown happens in the same task as setup — and
services requests via an in-memory queue. ``connect`` blocks on a
``ready`` event until the session task either finishes initialize or
reports a connect error; ``close`` sets a ``stop`` event and awaits
the task. ``list_tools`` / ``call_tool`` submit queued requests whose
results come back through per-call futures.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession
from mcp import types as mcp_types
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
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


@dataclass
class _PendingRequest:
    """One in-flight request the session task is servicing."""

    kind: str  # "list_tools" | "call_tool" | "list_resources" | "read_resource" | "list_prompts" | "get_prompt"
    name: str = ""
    arguments: dict[str, Any] | None = None
    uri: str = ""
    result: asyncio.Future[Any] | None = None


class _RemoteMCPBackend(MCPBackend):
    """Shared plumbing for HTTP and SSE transports.

    Subclasses override ``_transport_cm(record, headers, auth)`` to
    return an async context manager yielding ``(read, write)``.
    Everything else — session lifetime, request dispatch, cancellation
    — is handled here.
    """

    def __init__(self) -> None:
        self._tools_changed_cb: Any = None
        self._sampling_cb: Any = None
        self._record: MCPServerRecord | None = None
        self._session_task: asyncio.Task[None] | None = None
        self._ready_event: asyncio.Event | None = None
        self._stop_event: asyncio.Event | None = None
        self._request_queue: asyncio.Queue[_PendingRequest] | None = None
        self._connect_error: BaseException | None = None
        self._connected: bool = False

    # Subclass hook ---------------------------------------------------

    def _transport_cm(
        self,
        record: MCPServerRecord,
        headers: dict[str, str],
        auth: httpx.Auth | None,
    ) -> Any:
        """Return the SDK async context manager for this transport.

        Subclasses construct the specific ``streamablehttp_client`` /
        ``sse_client`` and return the unentered context manager.
        ``_run_session`` will ``async with`` it in the session task."""
        raise NotImplementedError

    # Public lifecycle ------------------------------------------------

    async def connect(self, record: MCPServerRecord) -> None:
        await self.connect_with_auth(record, auth=None)

    async def connect_with_auth(
        self,
        record: MCPServerRecord,
        *,
        auth: httpx.Auth | None,
    ) -> None:
        """Connect with an optional ``httpx.Auth`` override.

        Used by ``MCPService`` for OAuth-authenticated remotes — it
        passes an ``OAuthClientProvider`` instance here, which is
        itself an ``httpx.Auth`` and intercepts every HTTP request to
        inject bearer tokens / run the token refresh loop / drive the
        authorization flow on first use."""
        if self._session_task is not None:
            raise RuntimeError(f"{type(self).__name__} already connected")
        if not record.url:
            raise ValueError(f"{type(self).__name__} requires a URL")

        self._record = record
        self._ready_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._request_queue = asyncio.Queue()
        self._connect_error = None
        self._connected = False

        headers = _auth_headers(record)
        self._session_task = asyncio.create_task(
            self._run_session(record, headers, auth),
        )
        await self._ready_event.wait()
        if self._connect_error is not None:
            err = self._connect_error
            self._connect_error = None
            # Let the session task unwind cleanly.
            if self._session_task is not None:
                try:
                    await self._session_task
                except BaseException:
                    pass
            self._session_task = None
            raise err

    async def close(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        task = self._session_task
        self._session_task = None
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except TimeoutError:
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
            except BaseException:
                pass
        self._connected = False
        self._record = None
        self._ready_event = None
        self._stop_event = None
        self._request_queue = None

    async def list_tools(self) -> list[MCPToolSpec]:
        result = await self._submit(_PendingRequest(kind="list_tools"))
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
        result = await self._submit(
            _PendingRequest(kind="call_tool", name=name, arguments=arguments),
        )
        content = tuple(_translate_block(block) for block in result.content)
        structured = getattr(result, "structuredContent", None)
        return MCPToolResult(
            content=content,
            is_error=bool(result.isError),
            structured=dict(structured) if isinstance(structured, dict) else None,
        )

    async def list_resources(self) -> list[MCPResourceSpec]:
        result = await self._submit(_PendingRequest(kind="list_resources"))
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
        result = await self._submit(
            _PendingRequest(kind="read_resource", uri=uri),
        )
        return [_translate_resource_content(c) for c in result.contents]

    async def list_prompts(self) -> list[MCPPromptSpec]:
        result = await self._submit(_PendingRequest(kind="list_prompts"))
        return [_translate_prompt_spec(p) for p in result.prompts]

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str],
    ) -> MCPPromptResult:
        result = await self._submit(
            _PendingRequest(
                kind="get_prompt",
                name=name,
                arguments=dict(arguments),
            ),
        )
        return _translate_prompt_result(result)

    async def set_tools_changed_callback(self, callback: Any) -> None:
        self._tools_changed_cb = callback

    async def set_sampling_callback(self, callback: Any) -> None:
        self._sampling_cb = callback

    # Internals -------------------------------------------------------

    async def _submit(self, req: _PendingRequest) -> Any:
        if not self._connected or self._request_queue is None:
            raise RuntimeError(f"{type(self).__name__} is not connected")
        loop = asyncio.get_running_loop()
        req.result = loop.create_future()
        await self._request_queue.put(req)
        return await req.result

    async def _run_session(
        self,
        record: MCPServerRecord,
        headers: dict[str, str],
        auth: httpx.Auth | None,
    ) -> None:
        """Own the full session lifetime inside a single task.

        Opens the transport and ``ClientSession`` via ``async with``
        so their teardown happens in this task regardless of how the
        loop exits. Signals ``ready`` after initialize (or after a
        connect-time failure), then pumps the request queue until
        ``stop`` is set or a request fails with a transport error.

        Exception handling is deliberately defensive: anyio task
        groups wrap errors in ``BaseExceptionGroup`` and sometimes
        surface only a bare ``CancelledError`` from child-task
        cancellation, so we can't rely on the exception type or
        message to describe what actually happened. If we haven't
        signalled ready yet we report a synthetic
        ``ConnectionError`` and stash the original exception as the
        cause for anyone inspecting the chain.
        """
        assert self._ready_event is not None
        assert self._stop_event is not None
        assert self._request_queue is not None

        def _record_failure(exc: BaseException) -> None:
            if self._ready_event is None:
                return
            if self._ready_event.is_set():
                # Mid-session failure: fail any in-flight requests so
                # their futures resolve instead of hanging.
                self._fail_pending(exc)
                return
            err = ConnectionError(
                f"failed to connect to {record.url}: {type(exc).__name__}: {exc}".strip(": "),
            )
            err.__cause__ = exc if isinstance(exc, Exception) else None
            self._connect_error = err
            self._ready_event.set()

        try:
            async with self._transport_cm(record, headers, auth) as transport:
                read, write = _unpack_transport(transport)
                async with ClientSession(
                    read,
                    write,
                    message_handler=self._handle_message,
                    sampling_callback=self._sampling_cb,
                ) as session:
                    try:
                        await session.initialize()
                    except BaseException as exc:
                        _record_failure(exc)
                        return
                    self._connected = True
                    self._ready_event.set()
                    try:
                        await self._pump(session)
                    except BaseException as exc:
                        self._fail_pending(exc)
                        raise
        except (Exception, BaseExceptionGroup) as exc:
            _record_failure(exc)
        except asyncio.CancelledError as exc:
            _record_failure(exc)
            # Swallow — the task ends here by design.
        finally:
            self._connected = False

    async def _pump(self, session: ClientSession) -> None:
        """Service request queue entries against ``session`` until
        ``_stop_event`` fires or a transport error occurs."""
        assert self._stop_event is not None
        assert self._request_queue is not None
        stop_task = asyncio.create_task(self._stop_event.wait())
        try:
            while True:
                get_task = asyncio.create_task(self._request_queue.get())
                done, pending = await asyncio.wait(
                    {get_task, stop_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stop_task in done:
                    get_task.cancel()
                    with contextlib.suppress(Exception, asyncio.CancelledError):
                        await get_task
                    return
                req = get_task.result()
                result: Any
                try:
                    if req.kind == "list_tools":
                        result = await session.list_tools()
                    elif req.kind == "call_tool":
                        result = await session.call_tool(
                            req.name,
                            req.arguments or {},
                        )
                    elif req.kind == "list_resources":
                        result = await session.list_resources()
                    elif req.kind == "read_resource":
                        result = await session.read_resource(AnyUrl(req.uri))
                    elif req.kind == "list_prompts":
                        result = await session.list_prompts()
                    elif req.kind == "get_prompt":
                        result = await session.get_prompt(
                            req.name,
                            req.arguments or None,
                        )
                    else:  # pragma: no cover
                        raise ValueError(f"unknown request kind: {req.kind}")
                except BaseException as exc:
                    if req.result is not None and not req.result.done():
                        req.result.set_exception(_as_exception(exc))
                    raise
                else:
                    if req.result is not None and not req.result.done():
                        req.result.set_result(result)
        finally:
            stop_task.cancel()
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await stop_task

    def _fail_pending(self, exc: BaseException) -> None:
        if self._request_queue is None:
            return
        err = _as_exception(exc)
        while not self._request_queue.empty():
            req = self._request_queue.get_nowait()
            if req.result is not None and not req.result.done():
                req.result.set_exception(err)

    async def _handle_message(
        self,
        message: (
            RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult]
            | mcp_types.ServerNotification
            | Exception
        ),
    ) -> None:
        if isinstance(message, Exception):
            logger.debug(
                "MCP transport error for %s: %s",
                self._server_label(),
                message,
            )
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

    def _server_label(self) -> str:
        if self._record is None:
            return "<unknown>"
        return f"{self._record.name} ({self._record.id})"


class HttpMCPBackend(_RemoteMCPBackend):
    """Streamable HTTP transport — the modern unified MCP HTTP spec."""

    backend_name = "http"

    def _transport_cm(
        self,
        record: MCPServerRecord,
        headers: dict[str, str],
        auth: httpx.Auth | None,
    ) -> Any:
        assert record.url is not None
        return streamablehttp_client(
            url=record.url,
            headers=headers,
            auth=auth,
        )


class SseMCPBackend(_RemoteMCPBackend):
    """Server-Sent Events transport — legacy MCP HTTP spec.

    Kept alongside the Streamable HTTP transport because the older
    spec is still widely deployed (Claude Desktop connectors, etc.).
    Functionally equivalent from the service's point of view."""

    backend_name = "sse"

    def _transport_cm(
        self,
        record: MCPServerRecord,
        headers: dict[str, str],
        auth: httpx.Auth | None,
    ) -> Any:
        assert record.url is not None
        return sse_client(url=record.url, headers=headers, auth=auth)


def _unpack_transport(transport: Any) -> tuple[Any, Any]:
    """Both transports yield ``(read, write)`` — Streamable HTTP
    additionally yields a session-id getter which we discard because
    Part 2 doesn't use it."""
    if len(transport) == 2:
        return transport[0], transport[1]
    return transport[0], transport[1]


def _as_exception(exc: BaseException) -> Exception:
    """Coerce any ``BaseException`` into an ``Exception`` so futures
    carrying it don't reject ``set_exception``'s type check."""
    if isinstance(exc, Exception):
        return exc
    return RuntimeError(str(exc))


# ── module-level helpers ──────────────────────────────────────────────


def _auth_headers(record: MCPServerRecord) -> dict[str, str]:
    """Build the initial request headers for a remote record.

    Part 2.1 only wires the ``none`` and ``bearer`` auth kinds. The
    ``oauth`` kind is handled by passing an ``httpx.Auth`` into the
    transport's ``auth=`` argument; by the time Part 2.2 gets here we'll
    return an empty header dict for ``oauth`` and let the SDK's auth
    flow inject the Authorization header per request."""
    headers: dict[str, str] = {}
    auth = record.auth
    if auth.kind == "bearer" and auth.bearer_token:
        headers["Authorization"] = f"Bearer {auth.bearer_token}"
    return headers


def _translate_prompt_spec(prompt: Any) -> MCPPromptSpec:
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
    messages_raw = getattr(result, "messages", None) or []
    messages: list[MCPPromptMessage] = []
    for m in messages_raw:
        role_raw = getattr(m, "role", "user") or "user"
        role: Any = role_raw if role_raw in ("user", "assistant", "system") else "user"
        content = getattr(m, "content", None)
        block = (
            _translate_block(content)
            if content is not None
            else MCPContentBlock(type="text", text="")
        )
        messages.append(MCPPromptMessage(role=role, content=block))
    return MCPPromptResult(
        description=str(getattr(result, "description", "") or ""),
        messages=tuple(messages),
    )


def _translate_resource_content(content: Any) -> MCPResourceContent:
    """Flatten SDK ``TextResourceContents`` / ``BlobResourceContents``
    into Gilbert's flat ``MCPResourceContent``. Duplicated from
    ``mcp_stdio.py`` intentionally — see the note on ``_translate_block``
    for why each backend keeps its own translators."""
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
    return MCPResourceContent(uri=uri, kind="text", mime_type=mime)


def _translate_block(block: Any) -> MCPContentBlock:
    """Translate an MCP content block into Gilbert's flat dataclass.

    Duplicated from ``mcp_stdio.py`` intentionally — both transports
    use the same SDK types, but keeping the translator next to each
    backend means a future protocol change that lands in only one
    transport doesn't have to thread through a shared helper."""
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
