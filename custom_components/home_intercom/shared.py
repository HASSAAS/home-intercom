"""Shared modules — imported by both Docker (Flask) and HA integration.

Audio: both deployment modes use the same PCM→WAV conversion and WAV
concatenation. Audio constants (PCM_RATE, PCM_BPS, WAV_MAGIC,
WAV_HEADER_SIZE) come from const.py.

Playback: auto_pause.py holds the Tier-3 confirm→sleep→pause algorithm
shared by ha_client (sync REST/WS) and player.py (async HA services).

"""

from __future__ import annotations

import logging
import os
import shutil
import wave
from pathlib import Path
from typing import Any, Literal

try:
    from .const import CUSTOM_CHIME_FILENAME, DEFAULT_CHIME_STATIC_URL, MAX_CHIME_BYTES, PCM_BPS, WAV_MAGIC
except ImportError:
    from const import CUSTOM_CHIME_FILENAME, DEFAULT_CHIME_STATIC_URL, MAX_CHIME_BYTES, PCM_BPS, WAV_MAGIC

_LOGGER = logging.getLogger(__name__)


def is_wav(data: bytes) -> bool:
    """Check if raw data starts with WAV RIFF magic."""
    return data[: len(WAV_MAGIC)] == WAV_MAGIC


def handle_wav_passthrough(data: bytes, filepath: str) -> tuple[int, float]:
    """Complete WAV file → write as-is.

    Returns (sample_rate, duration_seconds).
    """
    with open(filepath, "wb") as f:
        f.write(data)
    with wave.open(filepath, "rb") as wf:
        rate = wf.getframerate()
        duration = wf.getnframes() / rate
    _LOGGER.info(
        "WAV passthrough %dB, %dHz, %dch, %dbit, %.1fs",
        len(data),
        rate,
        wf.getnchannels(),
        wf.getsampwidth() * 8,
        duration,
    )
    return rate, duration


def handle_pcm_to_wav(data: bytes, rate: int, filepath: str) -> float:
    """Raw 16-bit mono PCM → write WAV file with correct header.

    Returns duration_seconds.
    """
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(PCM_BPS)
        wf.setframerate(rate)
        wf.writeframes(data)
    duration = len(data) / (rate * PCM_BPS)
    file_size = os.path.getsize(filepath)
    _LOGGER.info(
        "WAV written: %s (%dB, %.1fs, %dHz)",
        os.path.basename(filepath),
        file_size,
        duration,
        rate,
    )
    return duration


def concat_wavs(chime_path: str, audio_path: str, output_path: str) -> float:
    """Prepend chime WAV to audio WAV. Returns total duration (seconds).

    Both files must have the same sample rate, channels, and sample width.
    On format mismatch, copies audio as-is and logs a warning.
    """
    with wave.open(chime_path, "rb") as wf_chime:
        chime_rate = wf_chime.getframerate()
        chime_frames = wf_chime.readframes(wf_chime.getnframes())
        chime_width = wf_chime.getsampwidth()
        chime_channels = wf_chime.getnchannels()

    with wave.open(audio_path, "rb") as wf_audio:
        audio_rate = wf_audio.getframerate()
        audio_frames = wf_audio.readframes(wf_audio.getnframes())
        audio_width = wf_audio.getsampwidth()
        audio_channels = wf_audio.getnchannels()

    if (chime_rate, chime_width, chime_channels) != (audio_rate, audio_width, audio_channels):
        _LOGGER.warning(
            "chime/audio format mismatch (chime=%dHz/%dB/%dch, audio=%dHz/%dB/%dch) — skipping chime",
            chime_rate,
            chime_width,
            chime_channels,
            audio_rate,
            audio_width,
            audio_channels,
        )
        shutil.copyfile(audio_path, output_path)
        with wave.open(output_path, "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()
        return duration

    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(audio_channels)
        wf.setsampwidth(audio_width)
        wf.setframerate(audio_rate)
        wf.writeframes(chime_frames + audio_frames)

    total_frames = (len(chime_frames) + len(audio_frames)) // (audio_width * audio_channels)
    duration = total_frames / audio_rate
    _LOGGER.info("chime + audio combined: %s (%.1fs)", os.path.basename(output_path), duration)
    return duration


# ═══════════════════════════════════════════════════════════════════════
# Custom chime — shared resolve / upload (issue #66)
# ═══════════════════════════════════════════════════════════════════════


def default_chime_path(integration_dir: Path) -> Path:
    """Bundled pre-announce WAV shipped with the integration."""
    return integration_dir / "static" / "pre_announce.wav"


def custom_chime_path(audio_dir: str) -> Path:
    """User-uploaded chime stored alongside recorded announcements."""
    return Path(audio_dir) / CUSTOM_CHIME_FILENAME


def has_custom_chime(audio_dir: str) -> bool:
    """True when a user-uploaded custom chime file exists."""
    return custom_chime_path(audio_dir).is_file()


def resolve_chime_wav(*, integration_dir: Path, audio_dir: str) -> Path:
    """Return custom chime if uploaded, else bundled default."""
    custom = custom_chime_path(audio_dir)
    if custom.is_file():
        return custom
    return default_chime_path(integration_dir)


def chime_public_url(
    base_url: str, *, audio_dir: str, deployment: Literal["ha", "docker"]
) -> str | None:
    """Public URL for MA pre_announce_url; None when using bundled default only."""
    if not has_custom_chime(audio_dir):
        return None
    base = base_url.rstrip("/")
    if deployment == "ha":
        return f"{base}/local/home_intercom_audio/{CUSTOM_CHIME_FILENAME}"
    return f"{base}/audio/{CUSTOM_CHIME_FILENAME}"


def chime_status_payload(
    *,
    base_url: str,
    audio_dir: str,
    deployment: Literal["ha", "docker"],
) -> dict[str, Any]:
    """Build GET /chime JSON — active URL plus whether it is custom."""
    custom = has_custom_chime(audio_dir)
    if custom:
        url = chime_public_url(base_url, audio_dir=audio_dir, deployment=deployment)
    else:
        url = DEFAULT_CHIME_STATIC_URL
    return {
        "custom": custom,
        "url": url or DEFAULT_CHIME_STATIC_URL,
        "default_url": DEFAULT_CHIME_STATIC_URL,
    }


def write_custom_chime_wav(data: bytes, audio_dir: str) -> None:
    """Persist uploaded WAV as the custom chime."""
    if len(data) > MAX_CHIME_BYTES:
        raise ValueError("chime too large")
    if not is_wav(data):
        raise ValueError("not a wav file")
    path = custom_chime_path(audio_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    _LOGGER.info("custom chime saved: %s (%dB)", path.name, len(data))


def delete_custom_chime(audio_dir: str) -> bool:
    """Remove custom chime file. Returns True if a file was deleted."""
    path = custom_chime_path(audio_dir)
    if path.is_file():
        path.unlink()
        _LOGGER.info("custom chime removed: %s", path.name)
        return True
    return False
