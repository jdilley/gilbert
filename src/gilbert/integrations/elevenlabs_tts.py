"""ElevenLabs TTS backend — text-to-speech via the ElevenLabs API."""

import logging
from typing import Any

import httpx

from gilbert.interfaces.tts import (
    AudioFormat,
    SynthesisRequest,
    SynthesisResult,
    TTSBackend,
    Voice,
)

logger = logging.getLogger(__name__)

# ElevenLabs API base
_BASE_URL = "https://api.elevenlabs.io/v1"

# Map our AudioFormat enum to ElevenLabs output_format parameter values
_FORMAT_MAP: dict[AudioFormat, str] = {
    AudioFormat.MP3: "mp3_44100_128",
    AudioFormat.WAV: "pcm_44100",
    AudioFormat.OGG: "ogg_vorbis",
    AudioFormat.PCM: "pcm_44100",
}

# Default silence padding in seconds
_DEFAULT_SILENCE_PADDING: float = 3.0

# PCM params used by ElevenLabs pcm_44100 format
_PCM_SAMPLE_RATE = 44100
_PCM_SAMPLE_WIDTH = 2  # 16-bit


def _generate_pcm_silence(seconds: float) -> bytes:
    """Generate raw 16-bit PCM silence at 44100 Hz."""
    num_samples = int(_PCM_SAMPLE_RATE * seconds)
    return b"\x00\x00" * num_samples


def _generate_mp3_silence(seconds: float) -> bytes:
    """Generate a minimal MP3 silence frame sequence.

    Each MPEG1 Layer 3 frame at 128kbps / 44100 Hz is 417 or 418 bytes
    and covers 1152 samples (~26.12ms). We emit enough zero-payload frames
    to cover the requested duration.
    """
    frame_samples = 1152
    frames_needed = int((_PCM_SAMPLE_RATE * seconds) / frame_samples) + 1
    # MPEG1, Layer 3, 128kbps, 44100 Hz, mono, no padding bit
    # Sync word: 0xFFE0 | version(11) | layer(01) | no CRC(1) = 0xFFFB
    # bitrate index 1001 (128k), sample rate 00 (44100), padding 0, private 0 = 0x90
    # mode 11 (mono), mode ext 00, copyright 0, original 0, emphasis 00 = 0xC0
    header = b"\xff\xfb\x90\xc0"
    # Frame size = 144 * 128000 / 44100 = 417.96 -> 417 bytes (no padding)
    # Payload = 417 - 4 header = 413 bytes of zeros
    frame = header + b"\x00" * 413
    return frame * frames_needed


class ElevenLabsTTS(TTSBackend):
    """ElevenLabs text-to-speech implementation."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._api_key: str = ""
        self._model_id: str = "eleven_turbo_v2_5"
        self._silence_padding: float = _DEFAULT_SILENCE_PADDING

    async def initialize(self, config: dict[str, object]) -> None:
        api_key = config.get("api_key")
        if not api_key or not isinstance(api_key, str):
            raise ValueError("ElevenLabs TTS requires 'api_key' in config")
        self._api_key = api_key

        if "model_id" in config:
            model_id = config["model_id"]
            if isinstance(model_id, str):
                self._model_id = model_id

        if "silence_padding" in config:
            val = config["silence_padding"]
            if isinstance(val, (int, float)):
                self._silence_padding = float(val)

        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
        logger.info(
            "ElevenLabs TTS initialized (model=%s, silence_padding=%.1fs)",
            self._model_id,
            self._silence_padding,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        if not request.voice_id:
            raise ValueError("voice_id is required for ElevenLabs TTS synthesis")

        client = self._require_client()

        output_format = _FORMAT_MAP.get(request.output_format, "mp3_44100_128")

        body: dict[str, Any] = {
            "text": request.text,
            "model_id": self._model_id,
        }

        voice_settings: dict[str, float] = {}
        if request.stability is not None:
            voice_settings["stability"] = request.stability
        if request.similarity_boost is not None:
            voice_settings["similarity_boost"] = request.similarity_boost
        if voice_settings:
            body["voice_settings"] = voice_settings

        response = await client.post(
            f"/text-to-speech/{request.voice_id}",
            json=body,
            params={"output_format": output_format},
        )
        response.raise_for_status()

        audio = response.content

        if self._silence_padding > 0:
            audio = self._append_silence(audio, request.output_format)

        characters_used = len(request.text)

        return SynthesisResult(
            audio=audio,
            format=request.output_format,
            characters_used=characters_used,
        )

    async def list_voices(self) -> list[Voice]:
        client = self._require_client()
        response = await client.get("/voices")
        response.raise_for_status()

        data = response.json()
        voices: list[Voice] = []
        for v in data.get("voices", []):
            voices.append(
                Voice(
                    voice_id=v["voice_id"],
                    name=v.get("name", v["voice_id"]),
                    language=v.get("fine_tuning", {}).get("language"),
                    description=v.get("description"),
                    labels=v.get("labels", {}),
                )
            )
        return voices

    async def get_voice(self, voice_id: str) -> Voice | None:
        client = self._require_client()
        response = await client.get(f"/voices/{voice_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()

        v = response.json()
        return Voice(
            voice_id=v["voice_id"],
            name=v.get("name", v["voice_id"]),
            language=v.get("fine_tuning", {}).get("language"),
            description=v.get("description"),
            labels=v.get("labels", {}),
        )

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("ElevenLabs TTS not initialized — call initialize() first")
        return self._client

    def _append_silence(self, audio: bytes, fmt: AudioFormat) -> bytes:
        """Append silence padding to the audio data."""
        if fmt == AudioFormat.MP3:
            return audio + _generate_mp3_silence(self._silence_padding)
        elif fmt in (AudioFormat.PCM, AudioFormat.WAV):
            return audio + _generate_pcm_silence(self._silence_padding)
        # For OGG or unknown formats, return as-is (can't trivially append)
        return audio
