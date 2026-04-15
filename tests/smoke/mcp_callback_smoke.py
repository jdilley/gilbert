"""Manual smoke test for the OAuth callback HTTP route.

Mounts the ``/api/mcp/oauth/callback`` route in a minimal FastAPI app
with a stub MCP service, then drives it with ``httpx.AsyncClient``
for every documented response path:

- success (pending flow resolved)
- malformed callback (missing code/state)
- auth portal error (``error=access_denied``)
- no flow in progress (unknown state)
- MCP subsystem not running

Run from the repo root::

    uv run python tests/smoke/mcp_callback_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from gilbert.web.routes.api import router  # noqa: E402

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"


class _StubMcp:
    def __init__(self, *, resolve: bool) -> None:
        self.resolve = resolve
        self.calls: list[tuple[str, str, str | None]] = []

    async def complete_oauth_callback(
        self, state: str, code: str, received_state: str | None,
    ) -> bool:
        self.calls.append((state, code, received_state))
        return self.resolve


class _StubServiceManager:
    def __init__(self, mcp) -> None:
        self._mcp = mcp

    def get_by_capability(self, name: str):
        if name == "mcp":
            return self._mcp
        return None


def _build_app(mcp) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.gilbert = SimpleNamespace(service_manager=_StubServiceManager(mcp))
    return app


async def main() -> int:
    results: list[tuple[bool, str]] = []

    def record(label: str, passed: bool, detail: str = "") -> None:
        mark = PASS if passed else FAIL
        results.append((passed, label))
        print(f"  {mark} {label}")
        if detail:
            print(f"      {detail}")

    print("=== MCP OAuth callback smoke test ===\n")

    async def get(url: str, mcp) -> httpx.Response:
        app = _build_app(mcp)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(url)

    # 1. Happy path — MCP resolves the flow
    mcp = _StubMcp(resolve=True)
    r = await get("/api/mcp/oauth/callback?code=abc&state=xyz", mcp)
    record(
        "success page rendered when flow resolves",
        r.status_code == 200 and "Sign-in complete" in r.text,
        f"status={r.status_code}",
    )
    record(
        "complete_oauth_callback called with (state, code, state)",
        mcp.calls == [("xyz", "abc", "xyz")],
        f"calls={mcp.calls}",
    )

    # 2. Auth portal error
    mcp = _StubMcp(resolve=False)
    r = await get(
        "/api/mcp/oauth/callback?error=access_denied&error_description=nope",
        mcp,
    )
    record(
        "auth portal error surfaces as 400 with error detail",
        r.status_code == 400 and "access_denied" in r.text,
        f"status={r.status_code}",
    )
    record(
        "auth portal error doesn't invoke MCP handler",
        mcp.calls == [],
    )

    # 3. Malformed callback (missing state)
    mcp = _StubMcp(resolve=True)
    r = await get("/api/mcp/oauth/callback?code=abc", mcp)
    record(
        "missing state returns 400 malformed page",
        r.status_code == 400 and "Malformed callback" in r.text,
        f"status={r.status_code}",
    )

    # 4. Unknown state (flow already expired)
    mcp = _StubMcp(resolve=False)
    r = await get("/api/mcp/oauth/callback?code=abc&state=stale", mcp)
    record(
        "unknown state returns 404 'no flow in progress'",
        r.status_code == 404 and "already been used" in r.text,
        f"status={r.status_code}",
    )

    # 5. MCP subsystem not running
    r = await get("/api/mcp/oauth/callback?code=abc&state=xyz", None)
    record(
        "MCP disabled returns 503",
        r.status_code == 503 and "MCP not running" in r.text,
        f"status={r.status_code}",
    )

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    print()
    if passed == total:
        print(f"{PASS} {passed}/{total} steps passed")
        return 0
    print(f"{FAIL} {passed}/{total} steps passed")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
