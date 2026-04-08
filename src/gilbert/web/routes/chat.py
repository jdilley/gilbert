"""Chat route — kept for backward compatibility.

All chat operations have moved to WebSocket RPC handlers on AIService.
This module is intentionally empty but remains registered so the
``/chat`` prefix doesn't 404 if anything references it.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/chat")
