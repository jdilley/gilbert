"""Google Workspace Directory integration — user/group provider.

Reads users and groups from Google Admin Directory API using a named
account profile from GoogleService. Acts as a UserProviderService so the
UserService can automatically sync external users into the local store.
"""

import logging
from typing import Any

from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver
from gilbert.interfaces.users import ExternalUser, UserProviderService

logger = logging.getLogger(__name__)


class GoogleDirectoryService(Service, UserProviderService):
    """Provides users and groups from Google Workspace Admin Directory.

    Capabilities: ``user_provider``.
    Requires: ``google_api``.
    """

    def __init__(self, account: str = "directory", domain: str = "") -> None:
        self._account = account
        self._domain = domain
        self._google: Any = None  # GoogleService, resolved at start
        self._cached_users: list[ExternalUser] | None = None
        self._cached_groups: list[dict[str, Any]] | None = None

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="google_directory",
            capabilities=frozenset({"user_provider"}),
            requires=frozenset({"google_api"}),
        )

    async def start(self, resolver: ServiceResolver) -> None:
        self._google = resolver.require_capability("google_api")
        logger.info(
            "Google Directory service started (account=%s, domain=%s)",
            self._account,
            self._domain,
        )

    async def stop(self) -> None:
        self._cached_users = None
        self._cached_groups = None

    # --- UserProviderService ---

    @property
    def provider_type(self) -> str:
        return "google"

    async def list_external_users(self) -> list[ExternalUser]:
        """Fetch all users from Google Workspace."""
        if self._cached_users is not None:
            return self._cached_users

        try:
            users = await self._fetch_users()
            groups = await self._fetch_groups_with_members()
            self._assign_groups_to_users(users, groups)
            self._cached_users = users
            logger.info("Fetched %d users from Google Directory", len(users))
            return users
        except Exception:
            logger.exception("Failed to fetch users from Google Directory")
            return []

    async def get_external_user(
        self, provider_user_id: str
    ) -> ExternalUser | None:
        """Look up a single user by Google user ID."""
        # Use cached list if available.
        users = await self.list_external_users()
        for user in users:
            if user.provider_user_id == provider_user_id:
                return user
        return None

    async def get_external_user_by_email(
        self, email: str
    ) -> ExternalUser | None:
        users = await self.list_external_users()
        for user in users:
            if user.email == email:
                return user
        return None

    async def list_groups(self) -> list[dict[str, Any]]:
        """List all groups from Google Workspace."""
        if self._cached_groups is not None:
            return self._cached_groups

        try:
            groups = await self._fetch_groups_with_members()
            self._cached_groups = groups
            return groups
        except Exception:
            logger.exception("Failed to fetch groups from Google Directory")
            return []

    def invalidate_cache(self) -> None:
        """Clear cached users/groups so next call re-fetches."""
        self._cached_users = None
        self._cached_groups = None

    # --- Internal ---

    async def _fetch_users(self) -> list[ExternalUser]:
        """Pull all non-suspended users from the directory."""
        directory = self._google.build_service(
            self._account, "admin", "directory_v1"
        )
        users: list[ExternalUser] = []

        request = directory.users().list(
            domain=self._domain,
            maxResults=500,
            orderBy="email",
            projection="full",
        )

        while request is not None:
            response = request.execute()

            for u in response.get("users", []):
                if u.get("suspended", False):
                    continue

                email = u.get("primaryEmail", "")
                if not email:
                    continue

                name = u.get("name", {})
                roles: list[str] = []
                if u.get("isAdmin", False):
                    roles.append("admin")

                # Collect email aliases.
                aliases = u.get("aliases", [])
                non_editable_aliases = u.get("nonEditableAliases", [])

                # Collect phone numbers.
                phones = [
                    {"value": p.get("value", ""), "type": p.get("type", "")}
                    for p in u.get("phones", [])
                ]

                # Collect addresses.
                addresses = [
                    {
                        "type": a.get("type", ""),
                        "formatted": a.get("formatted", ""),
                    }
                    for a in u.get("addresses", [])
                ]

                # Collect organizations (title, department, etc.).
                orgs = [
                    {
                        "title": o.get("title", ""),
                        "department": o.get("department", ""),
                        "name": o.get("name", ""),
                        "primary": o.get("primary", False),
                    }
                    for o in u.get("organizations", [])
                ]

                # Recovery info.
                recovery_email = u.get("recoveryEmail", "")
                recovery_phone = u.get("recoveryPhone", "")

                users.append(
                    ExternalUser(
                        provider_type="google",
                        provider_user_id=u.get("id", ""),
                        email=email,
                        display_name=name.get("fullName", email.split("@")[0]),
                        roles=roles,
                        metadata={
                            "google_id": u.get("id", ""),
                            "org_unit_path": u.get("orgUnitPath", "/"),
                            "is_admin": u.get("isAdmin", False),
                            "is_delegated_admin": u.get("isDelegatedAdmin", False),
                            "creation_time": u.get("creationTime", ""),
                            "last_login_time": u.get("lastLoginTime", ""),
                            "thumbnail_photo_url": u.get("thumbnailPhotoUrl", ""),
                            "aliases": aliases,
                            "non_editable_aliases": non_editable_aliases,
                            "phones": phones,
                            "addresses": addresses,
                            "organizations": orgs,
                            "recovery_email": recovery_email,
                            "recovery_phone": recovery_phone,
                            "agreed_to_terms": u.get("agreedToTerms", False),
                            "change_password_at_next_login": u.get(
                                "changePasswordAtNextLogin", False
                            ),
                            "ip_whitelisted": u.get("ipWhitelisted", False),
                            "include_in_global_address_list": u.get(
                                "includeInGlobalAddressList", True
                            ),
                            "customer_id": u.get("customerId", ""),
                            "etag": u.get("etag", ""),
                        },
                    )
                )

            request = directory.users().list_next(
                previous_request=request,
                previous_response=response,
            )

        return users

    async def _fetch_groups_with_members(self) -> list[dict[str, Any]]:
        """Fetch all groups and their members."""
        directory = self._google.build_service(
            self._account, "admin", "directory_v1"
        )
        groups: list[dict[str, Any]] = []

        request = directory.groups().list(
            domain=self._domain,
            maxResults=200,
        )

        while request is not None:
            response = request.execute()

            for g in response.get("groups", []):
                group_info: dict[str, Any] = {
                    "id": g.get("id", ""),
                    "email": g.get("email", ""),
                    "name": g.get("name", ""),
                    "description": g.get("description", ""),
                    "members": [],
                }

                # Fetch members.
                try:
                    mem_req = directory.members().list(
                        groupKey=g.get("email", ""),
                        maxResults=500,
                    )
                    while mem_req is not None:
                        mem_resp = mem_req.execute()
                        for m in mem_resp.get("members", []):
                            group_info["members"].append(m.get("email", ""))
                        mem_req = directory.members().list_next(
                            previous_request=mem_req,
                            previous_response=mem_resp,
                        )
                except Exception:
                    logger.debug(
                        "Could not list members for group %s",
                        g.get("email"),
                    )

                groups.append(group_info)

            request = directory.groups().list_next(
                previous_request=request,
                previous_response=response,
            )

        return groups

    @staticmethod
    def _assign_groups_to_users(
        users: list[ExternalUser], groups: list[dict[str, Any]]
    ) -> None:
        """Cross-reference group memberships onto user records."""
        email_to_user = {u.email: u for u in users}
        for group in groups:
            group_name = group.get("name", group.get("email", ""))
            for member_email in group.get("members", []):
                user = email_to_user.get(member_email)
                if user is not None:
                    user.groups.append(group_name)
