"""User backend interface — ABC for user CRUD, provider links, and roles."""

from abc import ABC, abstractmethod
from typing import Any


class UserBackend(ABC):
    """Abstract user storage.

    Provides domain-specific operations on top of the generic entity store
    so that services never need to construct raw storage queries for users.
    """

    # ---- User CRUD ----

    @abstractmethod
    async def create_user(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new user. Returns the stored entity."""

    @abstractmethod
    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        """Get a user by ID, or None."""

    @abstractmethod
    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """Look up a user by email address."""

    @abstractmethod
    async def get_user_by_provider_link(
        self, provider_type: str, provider_user_id: str
    ) -> dict[str, Any] | None:
        """Find a user linked to an external provider identity."""

    @abstractmethod
    async def update_user(self, user_id: str, data: dict[str, Any]) -> None:
        """Merge *data* into an existing user entity."""

    @abstractmethod
    async def delete_user(self, user_id: str) -> None:
        """Delete a user by ID."""

    @abstractmethod
    async def list_users(
        self, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List users with optional pagination."""

    # ---- Provider links ----

    @abstractmethod
    async def add_provider_link(
        self, user_id: str, provider_type: str, provider_user_id: str
    ) -> None:
        """Link an external provider identity to a local user."""

    @abstractmethod
    async def remove_provider_link(self, user_id: str, provider_type: str) -> None:
        """Remove an external provider link from a user."""

    # ---- Roles ----

    @abstractmethod
    async def set_roles(self, user_id: str, roles: set[str]) -> None:
        """Replace the user's roles with *roles*."""

    @abstractmethod
    async def get_roles(self, user_id: str) -> set[str]:
        """Return the user's current roles."""

    # ---- Provider users (remote user cache) ----

    @abstractmethod
    async def put_provider_user(
        self, provider_type: str, provider_user_id: str, data: dict[str, Any]
    ) -> None:
        """Store or update a remote user entity."""

    @abstractmethod
    async def get_provider_user(
        self, provider_type: str, provider_user_id: str
    ) -> dict[str, Any] | None:
        """Retrieve a cached remote user entity."""

    @abstractmethod
    async def list_provider_users(
        self, provider_type: str, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List cached remote users for a given provider."""
