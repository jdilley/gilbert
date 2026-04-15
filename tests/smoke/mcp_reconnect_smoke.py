"""Manual smoke test for Part 2.3 — reconnect + exponential backoff.

Scenarios:

1. **Delayed-start reconnect** — start the supervisor against a URL
   before the server exists. The supervisor should keep retrying
   until the server comes up, then connect.
2. **Mid-session drop + recovery** — start the server, connect, kill
   the server, verify the supervisor drops to reconnect state, bring
   the server back, verify it reconnects and rebuilds the tool
   cache.
3. **Graceful stop mid-backoff** — start a supervisor against a dead
   URL, let it bounce through a few retries, then ``_stop_client``
   and confirm it tears down cleanly (no hanging tasks, no stray
   subprocesses).

Run from the repo root::

    uv run python tests/smoke/mcp_reconnect_smoke.py
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from gilbert.core.services.mcp import MCPService  # noqa: E402
from gilbert.interfaces.mcp import MCPServerRecord  # noqa: E402
from tests.unit.test_mcp_service import FakeACL, FakeStorage  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mcp_http_echo_server.py"

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"


def pick_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
            s.close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"server on port {port} didn't come up within {timeout}s")


def start_server(port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(FIXTURE), "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _make_svc() -> MCPService:
    svc = MCPService()
    svc._enabled = True
    svc._storage = FakeStorage()
    svc._acl_svc = FakeACL()
    # Compress timings so the scenarios run in a few seconds, not minutes.
    svc._reconnect_initial_delay = 0.2
    svc._reconnect_max_delay = 1.0
    svc._connect_timeout = 3.0
    return svc


def _record(port: int, ttl: int = 2) -> MCPServerRecord:
    return MCPServerRecord(
        id="reconnect-smoke",
        name="Reconnect",
        slug="reconnect",
        transport="http",
        url=f"http://127.0.0.1:{port}/mcp",
        command=(),
        owner_id="alice",
        tool_cache_ttl_seconds=ttl,
    )


async def wait_until(predicate, *, timeout: float, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def scenario_delayed_start(report) -> None:
    """Start supervisor before the server exists; bring the server up
    mid-retry; verify supervisor connects."""
    port = pick_free_port()
    svc = _make_svc()
    record = _record(port)

    entry = await svc._start_client(record)
    assert entry is not None

    # Give it enough time to rack up a couple retries against a dead URL.
    got_retries = await wait_until(
        lambda: entry.retry_count >= 2,
        timeout=5.0,
    )
    report(
        "supervisor retries while server is down", got_retries, f"retry_count={entry.retry_count}"
    )

    # Now bring the server up.
    proc = start_server(port)
    try:
        wait_for_port(port)
        connected = await wait_until(
            lambda: entry.connected,
            timeout=5.0,
        )
        report(
            "supervisor reconnects once server comes up",
            connected,
            f"retry_count={entry.retry_count} connected={entry.connected}",
        )
        report(
            "retry_count reset after successful reconnect",
            entry.retry_count == 0,
            f"retry_count={entry.retry_count}",
        )
    finally:
        await svc._stop_client(record.id)
        proc.terminate()
        proc.wait(timeout=5)


async def scenario_mid_session_drop(report) -> None:
    """Connect, kill the server, verify the supervisor notices and
    drops to backoff; restart the server, verify reconnect."""
    port = pick_free_port()
    proc = start_server(port)
    wait_for_port(port)

    svc = _make_svc()
    record = _record(port, ttl=1)  # 1s health-check interval for quick detection
    entry = await svc._start_client(record)
    assert entry is not None
    connected = await wait_until(lambda: entry.connected, timeout=5.0)
    report("initial connect succeeded", connected, f"last_error={entry.last_error}")

    # Kill the server and wait for the health check to notice.
    proc.terminate()
    proc.wait(timeout=5)

    dropped = await wait_until(
        lambda: not entry.connected or entry.retry_count >= 1,
        timeout=5.0,
    )
    report(
        "supervisor notices the drop",
        dropped,
        f"retry_count={entry.retry_count} connected={entry.connected}",
    )

    # Bring the server back on the same port.
    proc = start_server(port)
    try:
        wait_for_port(port)
        reconnected = await wait_until(
            lambda: entry.connected,
            timeout=5.0,
        )
        report(
            "supervisor reconnects after the server returns",
            reconnected,
            f"retry_count={entry.retry_count} connected={entry.connected}",
        )
    finally:
        await svc._stop_client(record.id)
        proc.terminate()
        proc.wait(timeout=5)


async def scenario_stop_mid_backoff(report) -> None:
    """Let the supervisor bounce against a dead URL, then call
    ``_stop_client`` and confirm clean teardown."""
    port = pick_free_port()  # nothing listening
    svc = _make_svc()
    record = _record(port)

    entry = await svc._start_client(record)
    assert entry is not None
    got_retries = await wait_until(
        lambda: entry.retry_count >= 1,
        timeout=5.0,
    )
    report("supervisor entered backoff state", got_retries, f"retry_count={entry.retry_count}")

    # Stop and confirm the entry is gone.
    await svc._stop_client(record.id)
    report("stop_client removed the entry", record.id not in svc._clients)
    # Supervisor task should be done after cancellation.
    done = entry.supervisor is None or entry.supervisor.done()
    report("supervisor task finished", done)


async def main() -> int:
    results: list[tuple[bool, str]] = []

    def record(label: str, passed: bool, detail: str = "") -> None:
        mark = PASS if passed else FAIL
        results.append((passed, label))
        print(f"  {mark} {label}")
        if detail:
            print(f"      {detail}")

    print("=== MCP Part 2.3 reconnect smoke test ===\n")

    print("1. Delayed-start reconnect")
    await scenario_delayed_start(record)

    print("\n2. Mid-session drop + recovery")
    await scenario_mid_session_drop(record)

    print("\n3. Graceful stop mid-backoff")
    await scenario_stop_mid_backoff(record)

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
