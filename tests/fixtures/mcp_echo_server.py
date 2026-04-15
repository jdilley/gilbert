# mypy: ignore-errors
"""Tiny MCP server used by Gilbert's integration tests.

Advertises a single ``echo`` tool that mirrors its ``text`` argument
back. Speaks MCP over stdio using the official Python SDK, so it's a
production-shape server even though the logic is trivial — letting the
integration test exercise the full stdio transport, protocol
handshake, initialize round-trip, ``tools/list``, and ``tools/call``.

Lives under ``tests/fixtures/`` because it's spawned as a subprocess
by the integration test — it is never imported directly into the
Gilbert process, so strict mypy checking is waived for readability.
"""

from __future__ import annotations

import asyncio

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server


def main() -> None:
    app: Server = Server("gilbert-echo")

    @app.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="echo",
                description="Echo a string back to the caller.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The string to echo.",
                        },
                    },
                    "required": ["text"],
                },
            ),
            types.Tool(
                name="add",
                description="Add two integers.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "integer"},
                        "b": {"type": "integer"},
                    },
                    "required": ["a", "b"],
                },
            ),
        ]

    @app.list_resources()
    async def _list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri="echo://greeting",
                name="greeting",
                description="A canned greeting from the echo server.",
                mimeType="text/plain",
            ),
        ]

    @app.read_resource()
    async def _read_resource(uri):
        if str(uri) == "echo://greeting":
            return "hello from the echo server"
        raise ValueError(f"unknown resource: {uri}")

    @app.list_prompts()
    async def _list_prompts() -> list[types.Prompt]:
        return [
            types.Prompt(
                name="friendly_intro",
                description="Introduce Gilbert to a user by name.",
                arguments=[
                    types.PromptArgument(
                        name="user_name",
                        description="Name of the user to greet.",
                        required=True,
                    ),
                    types.PromptArgument(
                        name="tone",
                        description="Tone of the intro (casual / formal).",
                        required=False,
                    ),
                ],
            ),
        ]

    @app.get_prompt()
    async def _get_prompt(name, arguments):
        if name != "friendly_intro":
            raise ValueError(f"unknown prompt: {name}")
        user_name = (arguments or {}).get("user_name", "friend")
        tone = (arguments or {}).get("tone", "casual")
        text = f"Say hello to {user_name} in a {tone} tone."
        return types.GetPromptResult(
            description="A friendly intro.",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=text),
                ),
            ],
        )

    @app.call_tool()
    async def _call_tool(
        name: str,
        arguments: dict,
    ) -> list[types.TextContent]:
        if name == "echo":
            return [types.TextContent(type="text", text=f"echoed: {arguments['text']}")]
        if name == "add":
            total = int(arguments["a"]) + int(arguments["b"])
            return [types.TextContent(type="text", text=str(total))]
        raise ValueError(f"unknown tool: {name}")

    async def _run() -> None:
        async with stdio_server() as (read, write):
            await app.run(read, write, app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
