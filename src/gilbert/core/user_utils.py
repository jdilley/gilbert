"""User identity utilities — resolve user_id to display name."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def resolve_display_name(
    user_id: str,
    resolver: Any | None = None,
    first_name_only: bool = True,
) -> str:
    """Resolve a user_id to a human-readable display name.

    Looks up the user via the ``users`` capability from *resolver*.
    Falls back to parsing the user_id as an email or returning it as-is.

    Args:
        user_id: The internal user ID.
        resolver: A ``ServiceResolver`` for looking up the users service.
        first_name_only: If True, return only the first name.

    Returns:
        A human-readable name.
    """
    if resolver is not None:
        user_svc = resolver.get_capability("users")
        if user_svc is not None:
            try:
                user = await user_svc.backend.get_user(user_id)
                if user:
                    name = str(user.get("display_name", ""))
                    if name:
                        return name.split()[0] if first_name_only else name
            except Exception:
                logger.debug("Failed to resolve display name for %s", user_id, exc_info=True)

    # Fallback: parse from user_id
    if "@" in user_id:
        local = user_id.split("@")[0]
        return local.replace(".", " ").replace("_", " ").title()
    return user_id.split()[0] if " " in user_id else user_id
