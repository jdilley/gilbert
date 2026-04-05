"""Authentication interfaces — UserContext, AuthInfo, and AuthProvider ABC."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True)
class UserContext:
    """Immutable identity of the current user flowing through the system.

    Set at the request boundary (web middleware) or passed explicitly
    to service methods. The SYSTEM sentinel represents unauthenticated
    or system-level operations.
    """

    user_id: str
    email: str
    display_name: str
    roles: frozenset[str] = field(default_factory=frozenset)
    provider: str = "local"
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    SYSTEM: ClassVar[UserContext]


# Sentinel for unauthenticated / system-level operations.
UserContext.SYSTEM = UserContext(
    user_id="system",
    email="system@localhost",
    display_name="System",
    roles=frozenset(),
    provider="system",
)


@dataclass(frozen=True)
class AuthInfo:
    """Result returned by an AuthProvider after successful authentication.

    Contains provider-specific identity information that the AuthService
    uses to resolve or create a local user.
    """

    provider_type: str
    provider_user_id: str
    email: str
    display_name: str
    roles: frozenset[str] = field(default_factory=frozenset)
    raw: dict[str, Any] = field(default_factory=dict)


class AuthProvider(ABC):
    """Abstract authentication provider.

    Concrete implementations handle a specific authentication mechanism
    (local passwords, Google OAuth, Zoho, etc.). Multiple providers
    are aggregated by the AuthService.
    """

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Unique identifier for this provider (e.g., 'local', 'google')."""

    @abstractmethod
    async def initialize(self, config: dict[str, Any]) -> None:
        """Initialize with provider-specific configuration."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""

    @abstractmethod
    async def authenticate(self, credentials: dict[str, Any]) -> AuthInfo | None:
        """Authenticate with provider-specific credentials.

        Returns AuthInfo on success, None on failure.
        """

    async def sync_users(self) -> list[AuthInfo]:
        """Pull users from an external system. Default: no-op (local providers)."""
        return []

    async def get_role_mappings(self) -> dict[str, str]:
        """Map external groups/roles to Gilbert roles. Default: empty."""
        return {}


@dataclass
class LoginMethod:
    """Describes a login option to render on the login page.

    Each AuthenticationService provides one of these so the login page
    can display all available authentication options.
    """

    provider_type: str
    display_name: str
    # "form" = render an email/password form
    # "redirect" = render a button that redirects to an external auth URL
    method: str  # "form" or "redirect"
    # For "redirect" methods: the URL to redirect to
    redirect_url: str = ""
    # For "form" methods: the URL to POST the form to
    form_action: str = ""


class AuthenticationService(ABC):
    """Abstract authentication service.

    Each implementation handles a specific authentication mechanism and
    exposes enough metadata for the login page to render UI for it.
    Implementations should also be ``Service`` subclasses so they
    participate in the service lifecycle.
    """

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Unique identifier (e.g., ``'local'``, ``'google'``)."""

    @abstractmethod
    def get_login_method(self) -> LoginMethod:
        """Describe how this service appears on the login page."""

    @abstractmethod
    async def authenticate(self, credentials: dict[str, Any]) -> AuthInfo | None:
        """Authenticate. Returns AuthInfo on success, None on failure."""

    async def handle_callback(self, params: dict[str, Any]) -> AuthInfo | None:
        """Handle an OAuth/external callback. Default: not supported."""
        return None
