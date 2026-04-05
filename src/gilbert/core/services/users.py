"""User service — manages local user accounts, roles, and provider links."""

import json
import logging
from typing import Any

from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver
from gilbert.interfaces.storage import StorageBackend
from gilbert.interfaces.tools import (
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
)
from gilbert.interfaces.users import UserBackend
from gilbert.storage.user_storage import StorageUserBackend

logger = logging.getLogger(__name__)

_ROOT_USER_ID = "root"
_ROOT_EMAIL = "root@localhost"


class UserService(Service):
    """Wraps a UserBackend as a discoverable service.

    Always registered (users are foundational). On startup ensures the
    root user exists and creates storage indexes.
    """

    def __init__(
        self, root_password_hash: str = "", default_roles: list[str] | None = None
    ) -> None:
        self._root_password_hash = root_password_hash
        self._default_roles = default_roles or ["user"]
        self._backend: UserBackend | None = None

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="users",
            capabilities=frozenset({"users", "ai_tools"}),
            requires=frozenset({"entity_storage"}),
        )

    @property
    def backend(self) -> UserBackend:
        if self._backend is None:
            raise RuntimeError("UserService not started")
        return self._backend

    async def start(self, resolver: ServiceResolver) -> None:
        storage_svc = resolver.require_capability("entity_storage")
        storage: StorageBackend = storage_svc.backend  # type: ignore[attr-defined]

        backend = StorageUserBackend(storage)
        await backend.ensure_indexes()
        self._backend = backend

        await self._ensure_root_user()

    async def _ensure_root_user(self) -> None:
        """Create or update the root user on every startup."""
        assert self._backend is not None
        existing = await self._backend.get_user(_ROOT_USER_ID)
        if existing is None:
            logger.info("Creating root user")
            await self._backend.create_user(
                _ROOT_USER_ID,
                {
                    "email": _ROOT_EMAIL,
                    "display_name": "Root",
                    "password_hash": self._root_password_hash,
                    "is_root": True,
                    "roles": ["admin"],
                },
            )
        else:
            # Update password hash if it changed in config.
            if (
                self._root_password_hash
                and existing.get("password_hash") != self._root_password_hash
            ):
                logger.info("Updating root user password hash")
                await self._backend.update_user(
                    _ROOT_USER_ID, {"password_hash": self._root_password_hash}
                )

    # ---- Public API (delegates to backend with root-user guards) ----

    async def create_user(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new user with default roles applied."""
        roles = set(data.get("roles", []))
        roles.update(self._default_roles)
        data["roles"] = sorted(roles)
        return await self.backend.create_user(user_id, data)

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        return await self.backend.get_user(user_id)

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return await self.backend.get_user_by_email(email)

    async def delete_user(self, user_id: str) -> None:
        if user_id == _ROOT_USER_ID:
            raise ValueError("Cannot delete the root user")
        await self.backend.delete_user(user_id)

    async def add_provider_link(
        self, user_id: str, provider_type: str, provider_user_id: str
    ) -> None:
        if user_id == _ROOT_USER_ID:
            raise ValueError("Cannot link external providers to the root user")
        await self.backend.add_provider_link(user_id, provider_type, provider_user_id)

    # --- ToolProvider protocol ---

    @property
    def tool_provider_name(self) -> str:
        return "users"

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="list_users",
                description="List all local user accounts.",
                parameters=[
                    ToolParameter(
                        name="limit",
                        type=ToolParameterType.INTEGER,
                        description="Maximum number of users to return.",
                        required=False,
                    ),
                ],
            ),
            ToolDefinition(
                name="get_user",
                description="Get a user by ID.",
                parameters=[
                    ToolParameter(
                        name="user_id",
                        type=ToolParameterType.STRING,
                        description="The user ID to look up.",
                    ),
                ],
            ),
            ToolDefinition(
                name="create_user",
                description="Create a new local user account.",
                parameters=[
                    ToolParameter(
                        name="email",
                        type=ToolParameterType.STRING,
                        description="User email address.",
                    ),
                    ToolParameter(
                        name="display_name",
                        type=ToolParameterType.STRING,
                        description="Display name for the user.",
                    ),
                ],
            ),
        ]

    async def execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        match name:
            case "list_users":
                return await self._tool_list_users(arguments)
            case "get_user":
                return await self._tool_get_user(arguments)
            case "create_user":
                return await self._tool_create_user(arguments)
            case _:
                raise KeyError(f"Unknown tool: {name}")

    async def _tool_list_users(self, arguments: dict[str, Any]) -> str:
        limit = arguments.get("limit")
        users = await self.backend.list_users(limit=limit)
        # Strip password hashes from output.
        for u in users:
            u.pop("password_hash", None)
        return json.dumps(users)

    async def _tool_get_user(self, arguments: dict[str, Any]) -> str:
        user = await self.backend.get_user(arguments["user_id"])
        if user is None:
            return json.dumps({"error": f"User not found: {arguments['user_id']}"})
        user.pop("password_hash", None)
        return json.dumps(user)

    async def _tool_create_user(self, arguments: dict[str, Any]) -> str:
        import uuid

        user_id = f"usr_{uuid.uuid4().hex[:12]}"
        user = await self.create_user(
            user_id,
            {
                "email": arguments["email"],
                "display_name": arguments.get("display_name", ""),
            },
        )
        user.pop("password_hash", None)
        return json.dumps({"status": "ok", "user": user})
