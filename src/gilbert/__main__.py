"""Gilbert entrypoint — boots the application and runs the web server."""

import asyncio
import logging
import os
import signal

import uvicorn

from gilbert.config import DATA_DIR
from gilbert.core.app import Gilbert
from gilbert.web import create_app

logger = logging.getLogger(__name__)

PID_FILE = DATA_DIR / "gilbert.pid"

# Track signal count for force-exit
_signal_count = 0


def _write_pid() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def _remove_pid() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


async def main() -> None:
    global _signal_count

    gilbert = Gilbert.create()

    await gilbert.start()
    _write_pid()

    web_app = create_app(gilbert)

    uv_config = uvicorn.Config(
        web_app,
        host=gilbert.config.web.host,
        port=gilbert.config.web.port,
        log_level="info",
    )
    server = uvicorn.Server(uv_config)

    # Disable uvicorn's own signal handling — we manage it ourselves
    server.install_signal_handlers = lambda: None

    def _handle_signal(signum: int, frame: object) -> None:
        global _signal_count
        _signal_count += 1
        if _signal_count >= 2:
            logger.warning("Forced shutdown (signal %d)", _signal_count)
            _remove_pid()
            os._exit(1)
        logger.info("Shutdown signal received — press Ctrl+C again to force quit")
        server.should_exit = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        await server.serve()
    finally:
        await gilbert.stop()
        _remove_pid()


if __name__ == "__main__":
    asyncio.run(main())
