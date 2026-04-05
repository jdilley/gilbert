"""Tests for TTSService and TTS config parsing."""

from unittest.mock import AsyncMock

import pytest

from gilbert.config import GilbertConfig, TTSVoiceConfig
from gilbert.core.services.credentials import CredentialService
from gilbert.core.services.tts import TTSService
from gilbert.interfaces.credentials import ApiKeyCredential, UsernamePasswordCredential
from gilbert.interfaces.service import ServiceResolver
from gilbert.interfaces.tts import (
    AudioFormat,
    SynthesisRequest,
    SynthesisResult,
    TTSBackend,
    Voice,
)


class StubTTSBackend(TTSBackend):
    """In-memory TTS backend for testing."""

    def __init__(self) -> None:
        self.initialized = False
        self.closed = False
        self.init_config: dict[str, object] = {}
        self.last_request: SynthesisRequest | None = None
        self._voices: list[Voice] = [
            Voice(voice_id="v1", name="Alice", language="en"),
            Voice(voice_id="v2", name="Bob", language="en", description="Deep voice"),
        ]

    async def initialize(self, config: dict[str, object]) -> None:
        self.init_config = config
        self.initialized = True

    async def close(self) -> None:
        self.closed = True

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        self.last_request = request
        return SynthesisResult(
            audio=b"fake-audio-data",
            format=request.output_format,
            characters_used=len(request.text),
        )

    async def list_voices(self) -> list[Voice]:
        return list(self._voices)

    async def get_voice(self, voice_id: str) -> Voice | None:
        for v in self._voices:
            if v.voice_id == voice_id:
                return v
        return None


VOICES = {
    "default": TTSVoiceConfig(voice_id="v1"),
    "scary": TTSVoiceConfig(voice_id="v2"),
}


@pytest.fixture
def stub_backend() -> StubTTSBackend:
    return StubTTSBackend()


@pytest.fixture
def cred_service() -> CredentialService:
    return CredentialService({
        "elevenlabs": ApiKeyCredential(api_key="sk-test-key"),
        "other-login": UsernamePasswordCredential(username="u", password="p"),
    })


@pytest.fixture
def resolver(cred_service: CredentialService) -> ServiceResolver:
    mock = AsyncMock(spec=ServiceResolver)
    mock.require_capability.return_value = cred_service
    mock.get_capability.return_value = cred_service
    return mock


@pytest.fixture
def service(stub_backend: StubTTSBackend) -> TTSService:
    return TTSService(
        stub_backend,
        credential_name="elevenlabs",
        voices=VOICES,
        default_voice="default",
    )


# --- Service info ---


def test_service_info(service: TTSService) -> None:
    info = service.service_info()
    assert info.name == "tts"
    assert "text_to_speech" in info.capabilities
    assert "credentials" in info.requires


# --- Lifecycle ---


async def test_start_initializes_backend(
    stub_backend: StubTTSBackend, resolver: ServiceResolver
) -> None:
    svc = TTSService(stub_backend, credential_name="elevenlabs", config={"model_id": "v2"})
    await svc.start(resolver)

    assert stub_backend.initialized
    assert stub_backend.init_config["api_key"] == "sk-test-key"
    assert stub_backend.init_config["model_id"] == "v2"


async def test_start_requires_api_key_credential(
    stub_backend: StubTTSBackend,
) -> None:
    """Should raise if the credential is not an ApiKeyCredential."""
    cred_svc = CredentialService({
        "elevenlabs": UsernamePasswordCredential(username="u", password="p"),
    })
    resolver = AsyncMock(spec=ServiceResolver)
    resolver.require_capability.return_value = cred_svc

    svc = TTSService(stub_backend, credential_name="elevenlabs")
    with pytest.raises(TypeError, match="api_key credential"):
        await svc.start(resolver)


async def test_start_raises_on_missing_credential(
    stub_backend: StubTTSBackend,
) -> None:
    """Should raise if the named credential doesn't exist."""
    cred_svc = CredentialService({})
    resolver = AsyncMock(spec=ServiceResolver)
    resolver.require_capability.return_value = cred_svc

    svc = TTSService(stub_backend, credential_name="missing")
    with pytest.raises(LookupError, match="missing"):
        await svc.start(resolver)


async def test_stop_closes_backend(
    service: TTSService, stub_backend: StubTTSBackend, resolver: ServiceResolver
) -> None:
    await service.start(resolver)
    await service.stop()
    assert stub_backend.closed


# --- Voice resolution ---


def test_resolve_voice(service: TTSService) -> None:
    assert service.resolve_voice("default") == "v1"
    assert service.resolve_voice("scary") == "v2"


def test_resolve_voice_unknown(service: TTSService) -> None:
    with pytest.raises(KeyError, match="unknown"):
        service.resolve_voice("unknown")


def test_voices_property(service: TTSService) -> None:
    voices = service.voices
    assert "default" in voices
    assert "scary" in voices
    assert voices["default"].voice_id == "v1"


def test_default_voice_property(service: TTSService) -> None:
    assert service.default_voice == "default"


# --- Synthesis ---


async def test_synthesize(service: TTSService, resolver: ServiceResolver) -> None:
    await service.start(resolver)

    request = SynthesisRequest(text="Hello world", voice_id="v1")
    result = await service.synthesize(request)

    assert result.audio == b"fake-audio-data"
    assert result.format == AudioFormat.MP3
    assert result.characters_used == 11


async def test_synthesize_with_voice_name(
    service: TTSService, stub_backend: StubTTSBackend, resolver: ServiceResolver
) -> None:
    await service.start(resolver)

    request = SynthesisRequest(text="Boo!", voice_id="ignored")
    await service.synthesize(request, voice_name="scary")

    assert stub_backend.last_request is not None
    assert stub_backend.last_request.voice_id == "v2"


async def test_synthesize_with_default_voice(
    service: TTSService, stub_backend: StubTTSBackend, resolver: ServiceResolver
) -> None:
    await service.start(resolver)

    request = SynthesisRequest(text="Hello", voice_id="")
    await service.synthesize(request)

    assert stub_backend.last_request is not None
    assert stub_backend.last_request.voice_id == "v1"


async def test_synthesize_explicit_voice_id_used_when_no_name(
    service: TTSService, stub_backend: StubTTSBackend, resolver: ServiceResolver
) -> None:
    await service.start(resolver)

    request = SynthesisRequest(text="Hello", voice_id="explicit-id")
    await service.synthesize(request)

    assert stub_backend.last_request is not None
    assert stub_backend.last_request.voice_id == "explicit-id"


async def test_synthesize_with_options(service: TTSService, resolver: ServiceResolver) -> None:
    await service.start(resolver)

    request = SynthesisRequest(
        text="Test",
        voice_id="v1",
        output_format=AudioFormat.WAV,
        stability=0.5,
        similarity_boost=0.8,
    )
    result = await service.synthesize(request)
    assert result.format == AudioFormat.WAV


# --- Voice listing ---


async def test_list_voices(service: TTSService, resolver: ServiceResolver) -> None:
    await service.start(resolver)

    voices = await service.list_voices()
    assert len(voices) == 2
    assert voices[0].voice_id == "v1"
    assert voices[1].name == "Bob"


async def test_get_voice_found(service: TTSService, resolver: ServiceResolver) -> None:
    await service.start(resolver)

    voice = await service.get_voice("v1")
    assert voice is not None
    assert voice.name == "Alice"


async def test_get_voice_not_found(service: TTSService, resolver: ServiceResolver) -> None:
    await service.start(resolver)

    voice = await service.get_voice("nonexistent")
    assert voice is None


# --- Config parsing ---


def test_config_parses_tts_full() -> None:
    raw = {
        "tts": {
            "enabled": True,
            "backend": "elevenlabs",
            "credential": "my-elevenlabs",
            "default_voice": "default",
            "voices": {
                "default": {"voice_id": "abc123"},
                "scary": {"voice_id": "def456"},
            },
            "settings": {"model_id": "eleven_turbo_v2_5", "silence_padding": 5},
        }
    }
    config = GilbertConfig.model_validate(raw)
    assert config.tts.enabled is True
    assert config.tts.backend == "elevenlabs"
    assert config.tts.credential == "my-elevenlabs"
    assert config.tts.default_voice == "default"
    assert len(config.tts.voices) == 2
    assert config.tts.voices["default"].voice_id == "abc123"
    assert config.tts.voices["scary"].voice_id == "def456"
    assert config.tts.settings["model_id"] == "eleven_turbo_v2_5"
    assert config.tts.settings["silence_padding"] == 5


def test_config_tts_defaults() -> None:
    config = GilbertConfig.model_validate({})
    assert config.tts.enabled is False
    assert config.tts.backend == "elevenlabs"
    assert config.tts.credential == ""
    assert config.tts.default_voice == ""
    assert config.tts.voices == {}
    assert config.tts.settings == {}
