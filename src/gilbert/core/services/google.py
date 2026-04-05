"""Google API service — multi-account Google API client factory.

Supports multiple named service account profiles. Each consumer
(directory sync, email, calendar, etc.) references an account by name
to get an authenticated API client with the right credential and
delegated user.
"""

import json
import logging
from pathlib import Path
from typing import Any

from gilbert.config import GoogleConfig
from gilbert.interfaces.configuration import ConfigParam, Configurable
from gilbert.interfaces.credentials import ApiKeyPairCredential, GoogleServiceAccountCredential
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver
from gilbert.interfaces.tools import ToolParameterType

logger = logging.getLogger(__name__)


class _LoadedAccount:
    """A loaded and ready-to-use Google service account."""

    __slots__ = ("sa_info", "scopes", "delegated_user")

    def __init__(
        self,
        sa_info: dict[str, Any],
        scopes: list[str],
        delegated_user: str,
    ) -> None:
        self.sa_info = sa_info
        self.scopes = scopes
        self.delegated_user = delegated_user


class GoogleService(Service, Configurable):
    """Manages multiple Google service account profiles.

    Capabilities: ``google_api``.
    Requires: ``credentials``.
    """

    def __init__(self, config: GoogleConfig) -> None:
        self._config = config
        self._accounts: dict[str, _LoadedAccount] = {}
        self._oauth_client_id: str = ""
        self._oauth_client_secret: str = ""

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="google",
            capabilities=frozenset({"google_api"}),
            requires=frozenset({"credentials"}),
        )

    async def start(self, resolver: ServiceResolver) -> None:
        from gilbert.core.services.credentials import CredentialService

        cred_svc = resolver.require_capability("credentials")
        if not isinstance(cred_svc, CredentialService):
            raise TypeError("Expected CredentialService for 'credentials' capability")

        # Resolve OAuth credential (client_id + client_secret pair)
        if self._config.oauth_credential:
            oauth_cred = cred_svc.get(self._config.oauth_credential)
            if oauth_cred is None:
                logger.warning(
                    "Google OAuth credential '%s' not found",
                    self._config.oauth_credential,
                )
            elif isinstance(oauth_cred, ApiKeyPairCredential):
                self._oauth_client_id = oauth_cred.client_id
                self._oauth_client_secret = oauth_cred.client_secret
            else:
                logger.warning(
                    "Google OAuth credential '%s' is not an api_key_pair",
                    self._config.oauth_credential,
                )

        for account_name, account_cfg in self._config.accounts.items():
            cred = cred_svc.get(account_cfg.credential)
            if cred is None:
                logger.warning(
                    "Google account '%s': credential '%s' not found — skipping",
                    account_name,
                    account_cfg.credential,
                )
                continue
            if not isinstance(cred, GoogleServiceAccountCredential):
                logger.warning(
                    "Google account '%s': credential '%s' is not a "
                    "google_service_account — skipping",
                    account_name,
                    account_cfg.credential,
                )
                continue

            sa_path = Path(cred.service_account_file)
            if not sa_path.exists():
                logger.warning(
                    "Google account '%s': service account file not found: %s",
                    account_name,
                    cred.service_account_file,
                )
                continue

            with open(sa_path) as f:
                sa_info = json.load(f)

            # Merge scopes: account-level overrides credential-level.
            scopes = account_cfg.scopes if account_cfg.scopes else list(cred.scopes)

            self._accounts[account_name] = _LoadedAccount(
                sa_info=sa_info,
                scopes=scopes,
                delegated_user=account_cfg.delegated_user,
            )
            logger.info(
                "Google account '%s' loaded (delegated_user=%s, scopes=%d)",
                account_name,
                account_cfg.delegated_user or "(none)",
                len(scopes),
            )

        if not self._accounts:
            logger.warning("Google service started with no valid accounts")

        logger.info(
            "Google API service started — %d account(s)", len(self._accounts)
        )

    async def stop(self) -> None:
        self._accounts.clear()

    # --- Configurable ---

    @property
    def config_namespace(self) -> str:
        return "google"

    def config_params(self) -> list[ConfigParam]:
        return [
            ConfigParam(
                key="oauth_credential",
                type=ToolParameterType.STRING,
                description="Name of an api_key_pair credential with Google OAuth client_id/client_secret.",
                restart_required=True,
            ),
            ConfigParam(
                key="enabled",
                type=ToolParameterType.BOOLEAN,
                description="Whether the Google API service is enabled.",
                default=False,
                restart_required=True,
            ),
            ConfigParam(
                key="accounts",
                type=ToolParameterType.OBJECT,
                description="Named Google service account profiles (requires restart).",
                restart_required=True,
            ),
        ]

    async def on_config_changed(self, config: dict[str, Any]) -> None:
        pass  # All Google params are restart_required

    # --- Public API ---

    @property
    def oauth_client_id(self) -> str:
        return self._oauth_client_id

    @property
    def oauth_client_secret(self) -> str:
        return self._oauth_client_secret

    @property
    def account_names(self) -> list[str]:
        return sorted(self._accounts.keys())

    def get_credentials(
        self,
        account: str,
        scopes: list[str] | None = None,
        subject: str | None = None,
    ) -> Any:
        """Build google.oauth2 Credentials for a named account.

        Args:
            account: Name of the account profile (e.g., ``"directory"``).
            scopes: Override scopes (defaults to account-configured scopes).
            subject: Override delegated user (defaults to account config).

        Returns:
            A ``google.oauth2.service_account.Credentials`` instance.
        """
        from google.oauth2 import service_account

        loaded = self._accounts.get(account)
        if loaded is None:
            raise KeyError(
                f"Google account '{account}' not found. "
                f"Available: {', '.join(self.account_names)}"
            )

        creds = service_account.Credentials.from_service_account_info(
            loaded.sa_info,
            scopes=scopes or loaded.scopes,
        )

        delegate = subject or loaded.delegated_user
        if delegate:
            creds = creds.with_subject(delegate)

        return creds

    def build_service(
        self,
        account: str,
        service_name: str,
        version: str,
        scopes: list[str] | None = None,
        subject: str | None = None,
    ) -> Any:
        """Build an authenticated Google API service client.

        Args:
            account: Name of the account profile.
            service_name: API name (e.g., ``"admin"``, ``"gmail"``).
            version: API version (e.g., ``"directory_v1"``, ``"v1"``).
            scopes: Override scopes.
            subject: Override delegated user.

        Returns:
            A ``googleapiclient.discovery.Resource`` instance.
        """
        from googleapiclient.discovery import build

        creds = self.get_credentials(account, scopes=scopes, subject=subject)
        return build(service_name, version, credentials=creds)
