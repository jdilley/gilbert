"""Inbox route — kept for backward compatibility.

All inbox operations have moved to WebSocket RPC handlers on InboxService.
This module is intentionally empty but remains registered so the
``/inbox`` prefix doesn't 404 if anything references it.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/inbox")
