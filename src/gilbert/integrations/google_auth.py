"""Google OAuth authentication service.

Authenticates users via Google OAuth 2.0 authorization code flow.
Uses the tunnel service (ngrok) for the HTTPS callback URL when available.
"""

import logging
from typing import Any

from gilbert.interfaces.auth import (
    AuthenticationService,
    AuthInfo,
    LoginMethod,
)
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver

logger = logging.getLogger(__name__)


class GoogleAuthenticationService(Service, AuthenticationService):
    """Authenticates users via Google OAuth.

    Capabilities: ``authentication_provider``.
    Requires: ``google_api``.
    Optional: ``tunnel`` (for HTTPS callback URL).
    """

    def __init__(
        self,
        domain: str = "",
        use_tunnel: bool = True,
    ) -> None:
        self._domain = domain
        self._use_tunnel = use_tunnel
        self._google: Any = None
        self._tunnel: Any = None
        self._oauth_client_id: str = ""
        self._client_secret: str = ""

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="auth_google",
            capabilities=frozenset({"authentication_provider"}),
            requires=frozenset({"google_api"}),
            optional=frozenset({"tunnel"}),
        )

    async def start(self, resolver: ServiceResolver) -> None:
        self._google = resolver.require_capability("google_api")
        self._oauth_client_id = self._google.oauth_client_id
        self._client_secret = self._google.oauth_client_secret
        if self._use_tunnel:
            self._tunnel = resolver.get_capability("tunnel")

        if not self._oauth_client_id:
            logger.warning("Google OAuth client ID not configured")

        if self._tunnel:
            logger.info(
                "Google auth using tunnel callback: %s",
                self._tunnel.public_url_for("/auth/login/google/callback"),
            )

        logger.info(
            "Google authentication service started (domain=%s)",
            self._domain or "(any)",
        )

    async def stop(self) -> None:
        pass

    # --- AuthenticationService ---

    @property
    def provider_type(self) -> str:
        return "google"

    def get_login_method(self) -> LoginMethod:
        return LoginMethod(
            provider_type="google",
            display_name="Sign in with Google",
            method="redirect",
            redirect_url="/auth/login/google/start",
        )

    def get_callback_url(self, request_base_url: str = "") -> str:
        """Get the OAuth callback URL.

        Uses the tunnel (ngrok) URL if available, otherwise falls back
        to the request's base URL.
        """
        if self._tunnel and self._tunnel.public_url:
            return self._tunnel.public_url_for("/auth/login/google/callback")
        # Fallback to local URL.
        base = request_base_url.rstrip("/") if request_base_url else ""
        return f"{base}/auth/login/google/callback"

    async def authenticate(self, credentials: dict[str, Any]) -> AuthInfo | None:
        """Authenticate with a Google OAuth ID token.

        Expects: ``{"id_token": "..."}``.
        """
        id_token_str = credentials.get("id_token", "")
        if not id_token_str:
            return None

        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token

            if not self._oauth_client_id:
                logger.error("Google OAuth client ID not configured")
                return None

            info = id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
                self._oauth_client_id,
            )

            email = info.get("email", "")
            if not email:
                logger.warning("Google ID token missing email claim")
                return None

            if self._domain and info.get("hd") != self._domain:
                logger.warning(
                    "Google auth rejected: domain %s != %s",
                    info.get("hd"),
                    self._domain,
                )
                return None

            return AuthInfo(
                provider_type="google",
                provider_user_id=info.get("sub", ""),
                email=email,
                display_name=info.get("name", email.split("@")[0]),
                raw=dict(info),
            )

        except Exception:
            logger.exception("Google ID token verification failed")
            return None

    async def handle_callback(self, params: dict[str, Any]) -> AuthInfo | None:
        """Handle the OAuth callback with an authorization code."""
        code = params.get("code", "")
        if not code:
            return None

        try:
            import httpx

            redirect_uri = params.get("redirect_uri", "")

            data: dict[str, str] = {
                "code": code,
                "client_id": self._oauth_client_id,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
            if self._client_secret:
                data["client_secret"] = self._client_secret

            token_resp = httpx.post(
                "https://oauth2.googleapis.com/token",
                data=data,
            )
            if not token_resp.is_success:
                logger.error(
                    "Google token exchange failed: %s %s",
                    token_resp.status_code,
                    token_resp.text,
                )
                return None
            tokens = token_resp.json()

            id_token_str = tokens.get("id_token", "")
            if not id_token_str:
                logger.error("No id_token in Google OAuth response")
                return None

            return await self.authenticate({"id_token": id_token_str})

        except Exception:
            logger.exception("Google OAuth callback failed")
            return None

    @property
    def oauth_client_id(self) -> str:
        return self._oauth_client_id

    @property
    def domain(self) -> str:
        return self._domain
