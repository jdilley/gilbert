"""Inbox routes — browse and manage email messages (admin only)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from gilbert.core.app import Gilbert
from gilbert.core.services.inbox import InboxService
from gilbert.interfaces.auth import UserContext
from gilbert.web import templates
from gilbert.web.auth import require_role

router = APIRouter(prefix="/inbox")


def _get_inbox(gilbert: Gilbert) -> InboxService:
    svc = gilbert.service_manager.get_by_capability("email")
    if svc is None or not isinstance(svc, InboxService):
        raise HTTPException(status_code=503, detail="Inbox service not available")
    return svc


@router.get("")
async def inbox_page(
    request: Request,
    user: UserContext = Depends(require_role("admin")),
) -> Any:
    """Render the inbox browser UI."""
    return templates.TemplateResponse(request, "inbox.html", {
        "user": user,
    })


@router.get("/api/stats")
async def inbox_api_stats(
    request: Request,
    user: UserContext = Depends(require_role("admin")),
) -> JSONResponse:
    """Get inbox stats."""
    gilbert: Gilbert = request.app.state.gilbert
    inbox = _get_inbox(gilbert)
    stats = await inbox.get_stats()
    return JSONResponse(content=stats)


@router.get("/api/messages")
async def inbox_api_messages(
    request: Request,
    sender: str = "",
    subject: str = "",
    limit: int = 50,
    user: UserContext = Depends(require_role("admin")),
) -> JSONResponse:
    """List messages matching filters."""
    gilbert: Gilbert = request.app.state.gilbert
    inbox = _get_inbox(gilbert)
    messages = await inbox.search_messages(
        sender=sender, subject=subject, limit=limit,
        include_body=False,
    )
    return JSONResponse(content={
        "messages": [_summarize(m) for m in messages],
        "total": len(messages),
    })


@router.get("/api/messages/{message_id}")
async def inbox_api_message_detail(
    request: Request,
    message_id: str,
    user: UserContext = Depends(require_role("admin")),
) -> JSONResponse:
    """Get full message detail."""
    gilbert: Gilbert = request.app.state.gilbert
    inbox = _get_inbox(gilbert)
    record = await inbox.get_message(message_id)
    if not record:
        raise HTTPException(status_code=404, detail="Message not found")
    return JSONResponse(content=_detail(record))


@router.get("/api/threads/{thread_id}")
async def inbox_api_thread(
    request: Request,
    thread_id: str,
    user: UserContext = Depends(require_role("admin")),
) -> JSONResponse:
    """Get all messages in a thread."""
    gilbert: Gilbert = request.app.state.gilbert
    inbox = _get_inbox(gilbert)
    messages = await inbox.get_thread(thread_id)
    return JSONResponse(content={
        "thread_id": thread_id,
        "messages": [_detail(m) for m in messages],
    })


# --- Serialization helpers ---

def _summarize(record: dict[str, Any]) -> dict[str, Any]:
    """Summarize a message record for the list view."""
    snippet = record.get("snippet", "")
    if not snippet:
        body = record.get("body_text", "")
        snippet = body[:120] + ("..." if len(body) > 120 else "")
    return {
        "message_id": record.get("_id", ""),
        "thread_id": record.get("thread_id", ""),
        "subject": record.get("subject", ""),
        "sender_email": record.get("sender_email", ""),
        "sender_name": record.get("sender_name", ""),
        "date": record.get("date", ""),
        "is_inbound": record.get("is_inbound", True),
        "snippet": snippet,
    }


def _detail(record: dict[str, Any]) -> dict[str, Any]:
    """Full message detail for the detail view."""
    return {
        "message_id": record.get("_id", ""),
        "thread_id": record.get("thread_id", ""),
        "subject": record.get("subject", ""),
        "sender_email": record.get("sender_email", ""),
        "sender_name": record.get("sender_name", ""),
        "date": record.get("date", ""),
        "to": record.get("to", []),
        "cc": record.get("cc", []),
        "body_text": record.get("body_text", ""),
        "body_html": record.get("body_html", ""),
        "in_reply_to": record.get("in_reply_to", ""),
        "is_inbound": record.get("is_inbound", True),
    }
