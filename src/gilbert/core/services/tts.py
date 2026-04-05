"""TTS service — wraps a TTSBackend as a discoverable service."""

import logging
from dataclasses import replace

from gilbert.config import TTSVoiceConfig
from gilbert.interfaces.credentials import ApiKeyCredential
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver
from gilbert.interfaces.tts import (
    SynthesisRequest,
    SynthesisResult,
    TTSBackend,
    Voice,
)

logger = logging.getLogger(__name__)


class TTSService(Service):
    """Exposes a TTSBackend as a service with text_to_speech capability."""

    def __init__(
        self,
        backend: TTSBackend,
        credential_name: str,
        config: dict[str, object] | None = None,
        voices: dict[str, TTSVoiceConfig] | None = None,
        default_voice: str = "",
    ) -> None:
        self._backend = backend
        self._credential_name = credential_name
        self._config = config or {}
        self._voices = voices or {}
        self._default_voice = default_voice

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="tts",
            capabilities=frozenset({"text_to_speech"}),
            requires=frozenset({"credentials"}),
        )

    @property
    def backend(self) -> TTSBackend:
        return self._backend

    @property
    def default_voice(self) -> str:
        return self._default_voice

    @property
    def voices(self) -> dict[str, TTSVoiceConfig]:
        return dict(self._voices)

    def resolve_voice(self, name: str) -> str:
        """Resolve a named voice to its voice_id. Raises KeyError if not found."""
        voice_cfg = self._voices.get(name)
        if voice_cfg is None:
            raise KeyError(f"Unknown voice name: {name!r}")
        return voice_cfg.voice_id

    async def start(self, resolver: ServiceResolver) -> None:
        from gilbert.core.services.credentials import CredentialService

        cred_svc = resolver.require_capability("credentials")
        if not isinstance(cred_svc, CredentialService):
            raise TypeError("Expected CredentialService for 'credentials' capability")

        cred = cred_svc.require(self._credential_name)
        if not isinstance(cred, ApiKeyCredential):
            raise TypeError(
                f"Credential '{self._credential_name}' must be an api_key credential"
            )

        init_config: dict[str, object] = {**self._config, "api_key": cred.api_key}
        await self._backend.initialize(init_config)
        logger.info("TTS service started (credential=%s)", self._credential_name)

    async def stop(self) -> None:
        await self._backend.close()

    async def synthesize(
        self, request: SynthesisRequest, *, voice_name: str | None = None
    ) -> SynthesisResult:
        """Synthesize speech from text.

        If voice_name is given, its voice_id overrides the request's voice_id.
        If request.voice_id is empty and no voice_name is given, the default voice is used.
        """
        effective_request = self._resolve_request(request, voice_name)
        return await self._backend.synthesize(effective_request)

    async def list_voices(self) -> list[Voice]:
        """List available voices."""
        return await self._backend.list_voices()

    async def get_voice(self, voice_id: str) -> Voice | None:
        """Get a voice by ID."""
        return await self._backend.get_voice(voice_id)

    def _resolve_request(
        self, request: SynthesisRequest, voice_name: str | None
    ) -> SynthesisRequest:
        """Determine the effective voice_id for a request."""
        if voice_name is not None:
            return replace(request, voice_id=self.resolve_voice(voice_name))
        if not request.voice_id and self._default_voice:
            default_id = self._voices.get(self._default_voice)
            if default_id is not None:
                return replace(request, voice_id=default_id.voice_id)
        return request
