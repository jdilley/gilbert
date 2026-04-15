"""Unit tests for StdioMCPBackend — content translation & message routing.

The full transport round-trip lives in
``tests/integration/test_mcp_end_to_end.py`` because it needs a real
subprocess. These tests exercise the pure-Python paths that don't need
one: content block translation across every MCP block type, and
``tools/list_changed`` notification routing through the registered
callback.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gilbert.integrations.mcp_stdio import StdioMCPBackend


class TestTranslateBlock:
    def test_text_block(self) -> None:
        backend = StdioMCPBackend()
        block = SimpleNamespace(type="text", text="hello")
        result = backend._translate_block(block)
        assert result.type == "text"
        assert result.text == "hello"

    def test_image_block(self) -> None:
        backend = StdioMCPBackend()
        block = SimpleNamespace(type="image", data="abc123", mimeType="image/png")
        result = backend._translate_block(block)
        assert result.type == "image"
        assert result.data == "abc123"
        assert result.mime_type == "image/png"

    def test_audio_block(self) -> None:
        backend = StdioMCPBackend()
        block = SimpleNamespace(type="audio", data="xyz", mimeType="audio/mpeg")
        result = backend._translate_block(block)
        assert result.type == "audio"
        assert result.data == "xyz"
        assert result.mime_type == "audio/mpeg"

    def test_resource_block(self) -> None:
        backend = StdioMCPBackend()
        resource = SimpleNamespace(
            uri="file:///a.txt", text="contents", mimeType="text/plain",
        )
        block = SimpleNamespace(type="resource", resource=resource)
        result = backend._translate_block(block)
        assert result.type == "resource"
        assert result.uri == "file:///a.txt"
        assert result.text == "contents"
        assert result.mime_type == "text/plain"

    def test_resource_block_missing_resource(self) -> None:
        """Defensive: if the SDK ever ships a resource block without an
        inner ``resource``, we degrade to empty fields rather than
        crashing mid-tool-call."""
        backend = StdioMCPBackend()
        block = SimpleNamespace(type="resource", resource=None)
        result = backend._translate_block(block)
        assert result.type == "resource"
        assert result.uri == ""
        assert result.text == ""

    def test_unknown_block_type_stringifies(self) -> None:
        backend = StdioMCPBackend()
        block = SimpleNamespace(type="future", foo="bar")
        result = backend._translate_block(block)
        assert result.type == "text"
        assert "future" in result.text


class TestMessageHandler:
    @pytest.mark.asyncio
    async def test_tools_list_changed_invokes_callback(self) -> None:
        """A ToolListChangedNotification delivered through the message
        handler must fire the registered callback so the service can
        invalidate its tool cache."""
        from mcp import types

        backend = StdioMCPBackend()
        called: list[bool] = []

        async def cb() -> None:
            called.append(True)

        await backend.set_tools_changed_callback(cb)

        # Build a real ServerNotification wrapping ToolListChangedNotification
        notif = types.ServerNotification(
            types.ToolListChangedNotification(
                method="notifications/tools/list_changed",
            )
        )
        await backend._handle_message(notif)
        assert called == [True]

    @pytest.mark.asyncio
    async def test_exception_message_is_ignored(self) -> None:
        """Transport-level exceptions routed through the message handler
        shouldn't bubble up — they're logged and swallowed so the session
        keeps running."""
        backend = StdioMCPBackend()
        # Should not raise
        await backend._handle_message(RuntimeError("boom"))

    @pytest.mark.asyncio
    async def test_callback_error_is_logged_not_raised(self) -> None:
        """If the registered callback itself raises, the handler must
        catch the exception — otherwise a bad callback could poison the
        entire MCP session via anyio's task group."""
        from mcp import types

        backend = StdioMCPBackend()

        async def bad_cb() -> None:
            raise RuntimeError("callback broke")

        await backend.set_tools_changed_callback(bad_cb)
        notif = types.ServerNotification(
            types.ToolListChangedNotification(
                method="notifications/tools/list_changed",
            )
        )
        # Must not raise
        await backend._handle_message(notif)


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_close_before_connect_is_noop(self) -> None:
        """Service-level lifecycle sometimes closes a never-connected
        backend (e.g. when start() fails partway). The close must be a
        no-op rather than raising on an unset stack."""
        backend = StdioMCPBackend()
        await backend.close()

    @pytest.mark.asyncio
    async def test_list_tools_before_connect_raises(self) -> None:
        backend = StdioMCPBackend()
        with pytest.raises(RuntimeError, match="not connected"):
            await backend.list_tools()

    @pytest.mark.asyncio
    async def test_call_tool_before_connect_raises(self) -> None:
        backend = StdioMCPBackend()
        with pytest.raises(RuntimeError, match="not connected"):
            await backend.call_tool("x", {})
