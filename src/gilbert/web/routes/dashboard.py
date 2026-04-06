"""Dashboard route — main landing page with tool cards."""

from fastapi import APIRouter, Request

from gilbert.interfaces.auth import UserContext
from gilbert.web import templates

router = APIRouter()

# All available cards with their required role
_ALL_CARDS = [
    {
        "title": "Chat",
        "description": "Talk to Gilbert and get things done.",
        "url": "/chat",
        "icon": "&#128172;",  # speech bubble
        "required_role": "everyone",
    },
    {
        "title": "Documents",
        "description": "Browse and search the document knowledge store.",
        "url": "/documents",
        "icon": "&#128196;",  # page
        "required_role": "user",
    },
    {
        "title": "Screens",
        "description": "Set up remote display screens for documents and content.",
        "url": "/screens",
        "icon": "&#128187;",  # desktop computer
        "required_role": "everyone",
    },
    {
        "title": "Roles & Access",
        "description": "Manage roles, user permissions, and tool access.",
        "url": "/roles",
        "icon": "&#128274;",  # lock
        "required_role": "admin",
    },
    {
        "title": "System Browser",
        "description": "View services, capabilities, configuration, and tools.",
        "url": "/system",
        "icon": "&#9881;",  # gear
        "required_role": "admin",
    },
    {
        "title": "Inbox",
        "description": "Browse and manage email messages.",
        "url": "/inbox",
        "icon": "&#9993;",  # envelope
        "required_role": "admin",
    },
    {
        "title": "Entity Browser",
        "description": "Browse collections and entities in storage.",
        "url": "/entities",
        "icon": "&#128451;",  # file cabinet
        "required_role": "admin",
    },
]


def _get_effective_level(request: Request, user: UserContext) -> int:
    """Get user's effective RBAC level."""
    _BUILTIN = {"admin": 0, "user": 100, "everyone": 200}
    gilbert = getattr(request.app.state, "gilbert", None)
    if gilbert is not None:
        acl_svc = gilbert.service_manager.get_by_capability("access_control")
        if acl_svc is not None:
            return acl_svc.get_effective_level(user)
    if not user.roles:
        return 200
    return min(_BUILTIN.get(r, 100) for r in user.roles)


def _get_role_level(request: Request, role: str) -> int:
    """Get the level for a named role."""
    _BUILTIN = {"admin": 0, "user": 100, "everyone": 200}
    gilbert = getattr(request.app.state, "gilbert", None)
    if gilbert is not None:
        acl_svc = gilbert.service_manager.get_by_capability("access_control")
        if acl_svc is not None:
            return acl_svc.get_role_level(role)
    return _BUILTIN.get(role, 100)


@router.get("/")
async def dashboard(request: Request):  # type: ignore[no-untyped-def]
    user: UserContext = getattr(request.state, "user", UserContext.SYSTEM)

    effective = _get_effective_level(request, user)
    # SYSTEM bypass (-1) is for background jobs, not web visitors
    if effective < 0:
        effective = 200

    cards = [
        card for card in _ALL_CARDS
        if effective <= _get_role_level(request, card["required_role"])
    ]

    return templates.TemplateResponse(request, "dashboard.html", {
        "cards": cards,
        "user": user,
    })
