"""Tests for ElevenLabs TTS backend."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gilbert.integrations.elevenlabs_tts import ElevenLabsTTS, _generate_mp3_silence, _generate_pcm_silence
from gilbert.interfaces.tts import AudioFormat, SynthesisRequest


@pytest.fixture
def backend() -> ElevenLabsTTS:
    return ElevenLabsTTS()


# --- Initialization ---


async def test_initialize_sets_api_key(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test"})
    assert backend._api_key == "sk-test"
    assert backend._client is not None
    await backend.close()


async def test_initialize_default_model(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test"})
    assert backend._model_id == "eleven_turbo_v2_5"
    await backend.close()


async def test_initialize_custom_model(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test", "model_id": "eleven_multilingual_v2"})
    assert backend._model_id == "eleven_multilingual_v2"
    await backend.close()


async def test_initialize_default_silence_padding(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test"})
    assert backend._silence_padding == 3.0
    await backend.close()


async def test_initialize_custom_silence_padding(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test", "silence_padding": 5})
    assert backend._silence_padding == 5.0
    await backend.close()


async def test_initialize_zero_silence_padding(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test", "silence_padding": 0})
    assert backend._silence_padding == 0.0
    await backend.close()


async def test_initialize_requires_api_key(backend: ElevenLabsTTS) -> None:
    with pytest.raises(ValueError, match="api_key"):
        await backend.initialize({})


async def test_initialize_rejects_empty_api_key(backend: ElevenLabsTTS) -> None:
    with pytest.raises(ValueError, match="api_key"):
        await backend.initialize({"api_key": ""})


# --- Close ---


async def test_close_clears_client(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test"})
    await backend.close()
    assert backend._client is None


async def test_close_idempotent(backend: ElevenLabsTTS) -> None:
    await backend.close()  # no-op when not initialized


# --- Client guard ---


def test_require_client_raises_before_init(backend: ElevenLabsTTS) -> None:
    with pytest.raises(RuntimeError, match="not initialized"):
        backend._require_client()


# --- Silence generation ---


def test_generate_pcm_silence() -> None:
    silence = _generate_pcm_silence(1.0)
    # 44100 samples * 2 bytes per sample = 88200 bytes
    assert len(silence) == 88200
    assert silence == b"\x00" * 88200


def test_generate_pcm_silence_zero() -> None:
    silence = _generate_pcm_silence(0)
    assert silence == b""


def test_generate_mp3_silence_produces_bytes() -> None:
    silence = _generate_mp3_silence(1.0)
    assert len(silence) > 0
    # Should start with MP3 sync word
    assert silence[:2] == b"\xff\xfb"


def test_generate_mp3_silence_zero() -> None:
    # Even 0 seconds produces 1 frame due to rounding up
    silence = _generate_mp3_silence(0)
    assert len(silence) > 0


# --- Synthesize ---


async def test_synthesize_calls_api(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test", "silence_padding": 0})

    mock_response = AsyncMock()
    mock_response.content = b"audio-bytes"
    mock_response.raise_for_status = lambda: None

    with patch.object(backend._client, "post", return_value=mock_response) as mock_post:  # type: ignore[union-attr]
        request = SynthesisRequest(text="Hello", voice_id="voice123")
        result = await backend.synthesize(request)

        mock_post.assert_called_once()
        call_args = mock_post.call_args

        assert "/text-to-speech/voice123" in call_args.args[0]
        assert call_args.kwargs["json"]["text"] == "Hello"
        assert call_args.kwargs["json"]["model_id"] == "eleven_turbo_v2_5"
        assert call_args.kwargs["params"]["output_format"] == "mp3_44100_128"

    assert result.audio == b"audio-bytes"
    assert result.format == AudioFormat.MP3
    assert result.characters_used == 5
    await backend.close()


async def test_synthesize_appends_silence_padding(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test", "silence_padding": 1})

    mock_response = AsyncMock()
    mock_response.content = b"audio"
    mock_response.raise_for_status = lambda: None

    with patch.object(backend._client, "post", return_value=mock_response):  # type: ignore[union-attr]
        request = SynthesisRequest(text="Hi", voice_id="v1")
        result = await backend.synthesize(request)

    # Audio should be longer than just "audio" because silence was appended
    assert len(result.audio) > len(b"audio")
    # Should start with the original audio
    assert result.audio[:5] == b"audio"
    await backend.close()


async def test_synthesize_no_silence_when_zero(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test", "silence_padding": 0})

    mock_response = AsyncMock()
    mock_response.content = b"audio"
    mock_response.raise_for_status = lambda: None

    with patch.object(backend._client, "post", return_value=mock_response):  # type: ignore[union-attr]
        request = SynthesisRequest(text="Hi", voice_id="v1")
        result = await backend.synthesize(request)

    assert result.audio == b"audio"
    await backend.close()


async def test_synthesize_pcm_silence_padding(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test", "silence_padding": 1})

    mock_response = AsyncMock()
    mock_response.content = b"pcm-data"
    mock_response.raise_for_status = lambda: None

    with patch.object(backend._client, "post", return_value=mock_response):  # type: ignore[union-attr]
        request = SynthesisRequest(text="Hi", voice_id="v1", output_format=AudioFormat.PCM)
        result = await backend.synthesize(request)

    # Should have original + 88200 bytes of silence (1 second at 44100 Hz, 16-bit)
    assert len(result.audio) == len(b"pcm-data") + 88200
    await backend.close()


async def test_synthesize_passes_voice_settings(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test", "silence_padding": 0})

    mock_response = AsyncMock()
    mock_response.content = b"audio"
    mock_response.raise_for_status = lambda: None

    with patch.object(backend._client, "post", return_value=mock_response) as mock_post:  # type: ignore[union-attr]
        request = SynthesisRequest(
            text="Hi",
            voice_id="v1",
            stability=0.7,
            similarity_boost=0.9,
        )
        await backend.synthesize(request)

        body = mock_post.call_args.kwargs["json"]
        assert body["voice_settings"]["stability"] == 0.7
        assert body["voice_settings"]["similarity_boost"] == 0.9

    await backend.close()


# --- List voices ---


async def test_list_voices_parses_response(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test"})

    mock_response = MagicMock()
    mock_response.raise_for_status = lambda: None
    mock_response.json.return_value = {
        "voices": [
            {
                "voice_id": "abc",
                "name": "Rachel",
                "description": "Calm voice",
                "labels": {"accent": "american"},
                "fine_tuning": {"language": "en"},
            },
            {
                "voice_id": "def",
                "name": "Domi",
                "labels": {},
            },
        ]
    }

    with patch.object(backend._client, "get", return_value=mock_response):  # type: ignore[union-attr]
        voices = await backend.list_voices()

    assert len(voices) == 2
    assert voices[0].voice_id == "abc"
    assert voices[0].name == "Rachel"
    assert voices[0].language == "en"
    assert voices[0].labels == {"accent": "american"}
    assert voices[1].voice_id == "def"
    assert voices[1].language is None
    await backend.close()


# --- Get voice ---


async def test_get_voice_found(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test"})

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = lambda: None
    mock_response.json.return_value = {
        "voice_id": "abc",
        "name": "Rachel",
        "labels": {},
    }

    with patch.object(backend._client, "get", return_value=mock_response):  # type: ignore[union-attr]
        voice = await backend.get_voice("abc")

    assert voice is not None
    assert voice.voice_id == "abc"
    await backend.close()


async def test_get_voice_not_found(backend: ElevenLabsTTS) -> None:
    await backend.initialize({"api_key": "sk-test"})

    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch.object(backend._client, "get", return_value=mock_response):  # type: ignore[union-attr]
        voice = await backend.get_voice("nonexistent")

    assert voice is None
    await backend.close()
