"""Unit tests for HttpMCPBackend / SseMCPBackend — the paths that don't
need a real HTTP server.

Full HTTP round-trip is deferred — the SDK's own test suite covers the
transport, and Gilbert-specific behaviour (auth header building, URL
validation, registry registration) is what we need to pin down here.
Part 2.1 does not add an end-to-end integration test against a live
HTTP MCP server; that lands alongside reconnect/backoff in Part 2.3,
when the supervisor makes the round-trip worth the plumbing.
"""

from __future__ import annotations

import pytest

from gilbert.integrations.mcp_http import (
    HttpMCPBackend,
    SseMCPBackend,
    _auth_headers,
)
from gilbert.interfaces.mcp import MCPAuthConfig, MCPBackend, MCPServerRecord


class TestRegistry:
    def test_http_registered(self) -> None:
        assert MCPBackend.registered_backends()["http"] is HttpMCPBackend

    def test_sse_registered(self) -> None:
        assert MCPBackend.registered_backends()["sse"] is SseMCPBackend


class TestAuthHeaders:
    def _record(self, auth: MCPAuthConfig) -> MCPServerRecord:
        return MCPServerRecord(
            id="x",
            name="X",
            slug="x",
            transport="http",
            url="https://example.com/mcp",
            command=(),
            owner_id="alice",
            auth=auth,
        )

    def test_none_auth_emits_no_headers(self) -> None:
        headers = _auth_headers(self._record(MCPAuthConfig(kind="none")))
        assert "Authorization" not in headers

    def test_bearer_auth_emits_authorization(self) -> None:
        headers = _auth_headers(
            self._record(MCPAuthConfig(kind="bearer", bearer_token="abc123")),
        )
        assert headers["Authorization"] == "Bearer abc123"

    def test_bearer_auth_empty_token_does_not_emit_header(self) -> None:
        """Validation should have caught this, but be defensive — an
        empty bearer token that sneaks past validation shouldn't ship
        a malformed ``Authorization: Bearer `` header."""
        headers = _auth_headers(
            self._record(MCPAuthConfig(kind="bearer", bearer_token="")),
        )
        assert "Authorization" not in headers

    def test_oauth_auth_emits_no_headers(self) -> None:
        """OAuth is handled by httpx.Auth at request time — the initial
        headers dict stays empty until Part 2.2 wires the provider."""
        headers = _auth_headers(
            self._record(MCPAuthConfig(kind="oauth", oauth_scopes=("read",))),
        )
        assert "Authorization" not in headers


class TestConnect:
    @pytest.mark.asyncio
    async def test_http_connect_rejects_missing_url(self) -> None:
        backend = HttpMCPBackend()
        record = MCPServerRecord(
            id="x",
            name="Remote",
            slug="remote",
            transport="http",
            url=None,
            command=(),
            owner_id="alice",
        )
        with pytest.raises(ValueError, match="URL"):
            await backend.connect(record)

    @pytest.mark.asyncio
    async def test_sse_connect_rejects_missing_url(self) -> None:
        backend = SseMCPBackend()
        record = MCPServerRecord(
            id="x",
            name="Remote",
            slug="remote",
            transport="sse",
            url=None,
            command=(),
            owner_id="alice",
        )
        with pytest.raises(ValueError, match="URL"):
            await backend.connect(record)

    @pytest.mark.asyncio
    async def test_list_tools_before_connect_raises(self) -> None:
        backend = HttpMCPBackend()
        with pytest.raises(RuntimeError, match="not connected"):
            await backend.list_tools()

    @pytest.mark.asyncio
    async def test_close_before_connect_is_noop(self) -> None:
        backend = SseMCPBackend()
        await backend.close()  # should not raise
