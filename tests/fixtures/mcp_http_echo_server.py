# mypy: ignore-errors
"""Tiny HTTP MCP server used by Gilbert's smoke tests.

Mounts ``StreamableHTTPSessionManager`` under ``/mcp`` in a starlette
app served by uvicorn. Optionally enforces a bearer token via a tiny
middleware so bearer-auth smoke tests can verify Gilbert sends the
right header.

Run as::

    python tests/fixtures/mcp_http_echo_server.py --port 9876
    python tests/fixtures/mcp_http_echo_server.py --port 9876 --bearer s3cret

Lives under ``tests/fixtures/`` because it's spawned as a subprocess.
"""

from __future__ import annotations

import argparse
import contextlib
import os

import uvicorn
from mcp import types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount


def build_mcp_app() -> Server:
    app: Server = Server("gilbert-http-echo")

    @app.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="echo",
                description="Echo text back (HTTP transport smoke test).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            ),
        ]

    @app.call_tool()
    async def _call_tool(name, arguments):
        if name == "echo":
            return [types.TextContent(type="text", text=f"http-echo: {arguments['text']}")]
        raise ValueError(f"unknown tool: {name}")

    return app


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {self._token}":
            return Response("unauthorized", status_code=401)
        return await call_next(request)


def build_starlette_app(*, bearer: str | None) -> Starlette:
    mcp_app = build_mcp_app()
    manager = StreamableHTTPSessionManager(
        app=mcp_app,
        stateless=True,
    )

    async def mcp_handler(scope, receive, send):
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    middleware = []
    if bearer:
        middleware.append(Middleware(BearerAuthMiddleware, token=bearer))

    return Starlette(
        lifespan=lifespan,
        routes=[Mount("/mcp", app=mcp_handler)],
        middleware=middleware,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--bearer", type=str, default=None)
    args = parser.parse_args()

    bearer = args.bearer or os.environ.get("MCP_ECHO_BEARER") or None
    app = build_starlette_app(bearer=bearer)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
