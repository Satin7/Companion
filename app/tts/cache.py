"""TTSCache — disk-backed TTS audio cache with content-based dedup.

Caches synthesised MP3 bytes keyed by ``SHA256(text + voice)`` so identical
requests (same text, same voice) never re-hit the TTS provider.

Files are stored under ``data/tts_cache/`` and survive server restarts.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from app.tts import get_tts_provider

_log = logging.getLogger("companion.tts.cache")

_CACHE_DIR = Path(os.getenv("TTS_CACHE_DIR", "data/tts_cache"))


class TTSCache:
    """Disk-backed cache for TTS audio bytes."""

    def __init__(self) -> None:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _cache_key(text: str, voice: str | None) -> str:
        """Deterministic cache key: hex digest of ``<voice>|<text>``."""
        raw = f"{voice or ''}|{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _file_path(self, audio_id: str) -> Path:
        return _CACHE_DIR / audio_id

    async def synthesize(self, text: str, voice: str | None = None) -> str:
        """Synthesise *text* and return an opaque ``audio_id``.

        If the same (text, voice) pair was already cached (on disk) the call
        is a no-op and the existing id is returned immediately.
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("TTS text must be non-empty")

        audio_id = self._cache_key(text, voice)
        filepath = self._file_path(audio_id)

        if filepath.exists():
            size = filepath.stat().st_size
            _log.debug("TTS cache hit id=%s size=%d", audio_id[:12], size)
            return audio_id

        provider = get_tts_provider()
        _log.info("TTS synthesising len=%d voice=%s provider=%s", len(text), voice or "default", type(provider).__name__)
        mp3_bytes = await provider.synthesize(text, voice=voice)

        # Write atomically: temp file → rename
        tmp = filepath.with_suffix(filepath.suffix + ".tmp")
        tmp.write_bytes(mp3_bytes)
        tmp.rename(filepath)

        _log.info("TTS cached id=%s bytes=%d", audio_id[:12], len(mp3_bytes))
        return audio_id

    def get(self, audio_id: str) -> Optional[bytes]:
        """Retrieve cached MP3 bytes by *audio_id*, or ``None``."""
        filepath = self._file_path(audio_id)
        if not filepath.exists():
            return None
        try:
            return filepath.read_bytes()
        except OSError:
            _log.warning("TTS cache read failed id=%s", audio_id[:12])
            return None

    def __len__(self) -> int:
        return len(list(_CACHE_DIR.iterdir()))
