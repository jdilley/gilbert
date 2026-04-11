"""Shared chat helpers — re-exports from ``gilbert.core.chat``.

Web-layer callers can continue to import from here. Core services
should import directly from ``gilbert.core.chat`` to avoid depending
on the web package.
"""

from gilbert.core.chat import (  # noqa: F401
    build_room_context,
    check_conversation_access,
    conv_summary,
    mentions_gilbert,
    publish_event,
)

__all__ = [
    "build_room_context",
    "check_conversation_access",
    "conv_summary",
    "mentions_gilbert",
    "publish_event",
]
