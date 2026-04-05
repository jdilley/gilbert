"""Dashboard route — main landing page with tool cards."""

from fastapi import APIRouter, Request

from gilbert.web import templates

router = APIRouter()


@router.get("/")
async def dashboard(request: Request):  # type: ignore[no-untyped-def]
    cards = [
        {
            "title": "System Browser",
            "description": "View services, capabilities, configuration, and tools.",
            "url": "/system",
            "icon": "&#9881;",  # gear
        },
        {
            "title": "Entity Browser",
            "description": "Browse collections and entities in storage.",
            "url": "/entities",
            "icon": "&#128451;",  # file cabinet
        },
        {
            "title": "Chat",
            "description": "Talk to Gilbert and get things done.",
            "url": "/chat",
            "icon": "&#128172;",  # speech bubble
        },
    ]
    return templates.TemplateResponse(request, "dashboard.html", {"cards": cards})
