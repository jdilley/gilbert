"""Tunnel service — provides public HTTPS URLs via ngrok.

Starts an ngrok tunnel to the local web server so external services
(Google OAuth, webhooks, etc.) can reach Gilbert over HTTPS.
"""

import logging
from typing import Any

from gilbert.config import TunnelConfig
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver

logger = logging.getLogger(__name__)


class TunnelService(Service):
    """Manages an ngrok tunnel for public HTTPS access.

    Capabilities: ``tunnel``.
    Requires: ``credentials`` (optional — only if auth token configured).
    """

    def __init__(self, config: TunnelConfig, local_port: int = 8765) -> None:
        self._config = config
        self._local_port = local_port
        self._tunnel: Any = None
        self._public_url: str = ""

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="tunnel",
            capabilities=frozenset({"tunnel"}),
            optional=frozenset({"credentials"}),
        )

    async def start(self, resolver: ServiceResolver) -> None:
        from pyngrok import conf, ngrok

        # Configure auth token if provided.
        if self._config.credential:
            cred_svc = resolver.get_capability("credentials")
            if cred_svc is not None:
                from gilbert.interfaces.credentials import ApiKeyCredential

                cred = cred_svc.get(self._config.credential)  # type: ignore[union-attr]
                if isinstance(cred, ApiKeyCredential):
                    conf.get_default().auth_token = cred.api_key
                    logger.info("Ngrok auth token configured")

        # Start the tunnel.
        options: dict[str, Any] = {"addr": str(self._local_port)}
        if self._config.domain:
            options["domain"] = self._config.domain

        self._tunnel = ngrok.connect(**options)
        self._public_url = self._tunnel.public_url

        # Ensure HTTPS.
        if self._public_url.startswith("http://"):
            self._public_url = self._public_url.replace("http://", "https://", 1)

        logger.info("Tunnel started: %s -> localhost:%d", self._public_url, self._local_port)

    async def stop(self) -> None:
        if self._tunnel is not None:
            from pyngrok import ngrok

            try:
                ngrok.disconnect(self._tunnel.public_url)
            except Exception:
                logger.debug("Error disconnecting tunnel")
            self._tunnel = None
            self._public_url = ""
            logger.info("Tunnel stopped")

    # --- Public API ---

    @property
    def public_url(self) -> str:
        """The public HTTPS URL (e.g., ``https://abc123.ngrok.io``)."""
        return self._public_url

    def public_url_for(self, path: str) -> str:
        """Build a full public URL for a path (e.g., ``/auth/login/google/callback``)."""
        base = self._public_url.rstrip("/")
        path = path if path.startswith("/") else f"/{path}"
        return f"{base}{path}"
