"""WebSocket route — streams events from the event bus to connected clients."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from gilbert.core.app import Gilbert
from gilbert.interfaces.events import Event

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/events")
async def event_stream(websocket: WebSocket) -> None:
    """Stream events to a connected WebSocket client.

    Authenticates via the session cookie (same as HTTP requests).
    Subscribes to all events and forwards them as JSON.
    Events are filtered by the user's role — admin sees everything,
    others only see non-sensitive events.
    """
    await websocket.accept()

    gilbert: Gilbert | None = getattr(websocket.app.state, "gilbert", None)
    if gilbert is None:
        await websocket.close(code=1011, reason="Gilbert not available")
        return

    # Authenticate from cookie
    user_id = "guest"
    user_roles: frozenset[str] = frozenset({"everyone"})
    session_id = websocket.cookies.get("gilbert_session")
    if session_id:
        auth_svc = gilbert.service_manager.get_by_capability("authentication")
        if auth_svc is not None:
            ctx = await auth_svc.validate_session(session_id)
            if ctx is not None:
                user_id = ctx.user_id
                user_roles = ctx.roles

    is_admin = "admin" in user_roles

    # Subscribe to all events
    event_bus_svc = gilbert.service_manager.get_by_capability("event_bus")
    if event_bus_svc is None:
        await websocket.close(code=1011, reason="Event bus not available")
        return

    from gilbert.core.services.event_bus import EventBusService

    if not isinstance(event_bus_svc, EventBusService):
        await websocket.close(code=1011, reason="Event bus not available")
        return

    bus = event_bus_svc.bus

    # Track which shared conversations this user belongs to.
    # Seeded on connect, updated by membership events.
    shared_conv_ids: set[str] = set()

    # Seed membership set on connect
    ai_svc = gilbert.service_manager.get_by_capability("ai_chat")
    if ai_svc is not None:
        try:
            convos = await ai_svc.list_shared_conversations(user_id=user_id, limit=200)
            for c in convos:
                cid = c.get("_id", "")
                if cid and c.get("_is_member", False):
                    shared_conv_ids.add(cid)
        except Exception:
            logger.debug("Failed to seed shared memberships", exc_info=True)

    # Queue for events to send to this client
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)

    # Events that are admin-only (contain sensitive system info)
    _ADMIN_PREFIXES = ("service.", "acl.")

    async def _on_event(event: Event) -> None:
        """Push event to the client queue if they have access."""
        if not is_admin and any(event.event_type.startswith(p) for p in _ADMIN_PREFIXES):
            return

        conv_id = event.data.get("conversation_id", "")

        # Update membership tracking FIRST (before filtering)
        if event.event_type == "chat.member.joined":
            if event.data.get("user_id") == user_id:
                shared_conv_ids.add(conv_id)
        elif event.event_type in ("chat.member.left", "chat.member.kicked"):
            if event.data.get("user_id") == user_id:
                shared_conv_ids.discard(conv_id)
        elif event.event_type in ("chat.conversation.abandoned", "chat.conversation.destroyed"):
            shared_conv_ids.discard(conv_id)
        elif event.event_type == "chat.conversation.created":
            members = event.data.get("members", [])
            if any(m.get("user_id") == user_id for m in members):
                shared_conv_ids.add(conv_id)

        # Filter shared conversation events by membership
        if event.event_type.startswith(("chat.message.", "chat.member.")):
            if conv_id and conv_id not in shared_conv_ids:
                # Allow join events targeted at this user (they just got added above)
                if not (event.event_type == "chat.member.joined"
                        and event.data.get("user_id") == user_id):
                    return
            # Filter by visible_to if present (for private messages)
            visible_to = event.data.get("visible_to")
            if visible_to is not None and user_id not in visible_to:
                return

        try:
            queue.put_nowait({
                "event_type": event.event_type,
                "data": event.data,
                "source": event.source,
                "timestamp": event.timestamp.isoformat() if event.timestamp else "",
            })
        except asyncio.QueueFull:
            pass  # Drop events if client can't keep up

    unsubscribe = bus.subscribe_pattern("*", _on_event)

    logger.debug("WebSocket connected: user=%s, admin=%s", user_id, is_admin)

    try:
        # Run send and receive concurrently
        send_task = asyncio.create_task(_send_events(websocket, queue))
        recv_task = asyncio.create_task(_receive_messages(websocket))

        # Wait for either to finish (disconnect or error)
        done, pending = await asyncio.wait(
            {send_task, recv_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("WebSocket error", exc_info=True)
    finally:
        unsubscribe()
        logger.debug("WebSocket disconnected: user=%s", user_id)


async def _send_events(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    """Send queued events to the WebSocket client."""
    while True:
        event_data = await queue.get()
        try:
            await websocket.send_json(event_data)
        except Exception:
            return


async def _receive_messages(websocket: WebSocket) -> None:
    """Receive messages from the client (keep connection alive, handle pings)."""
    while True:
        try:
            await websocket.receive_text()
        except WebSocketDisconnect:
            return
        except Exception:
            return
