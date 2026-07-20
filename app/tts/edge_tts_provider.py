"""Microsoft Edge TTS provider — free, no API key, natural Chinese voices.

Uses the ``edge-tts`` library which talks to Microsoft's free TTS service.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # edge_tts is imported lazily in synthesize()

from app.tts.base import BaseTTSProvider

_log = logging.getLogger("companion.tts.edge")

# Prefer female Chinese voices first; fall back to male.
_DEFAULT_VOICES = [
    "zh-CN-XiaoxiaoNeural",   # 晓晓 — 活泼女声
    "zh-CN-XiaoyiNeural",     # 晓伊 — 温柔女声
    "zh-CN-YunxiNeural",      # 云希 — 自然男声
]


class EdgeTTSProvider(BaseTTSProvider):
    """TTS via Microsoft Edge's free public endpoint."""

    def __init__(self) -> None:
        self._voice: str | None = None  # resolved on first call

    async def _resolve_voice(self, requested: str | None) -> str:
        """Pick the best available voice, falling back gracefully."""
        import edge_tts  # lazy import — only needed when this provider is used

        candidates = [requested] if requested else _DEFAULT_VOICES

        try:
            voices = await edge_tts.list_voices()
            available = {v["ShortName"] for v in voices}
        except Exception:
            _log.warning("Cannot list Edge voices — using default set")
            available = set(_DEFAULT_VOICES)

        for name in candidates:
            if name in available:
                self._voice = name
                return name

        # Last resort — just return the first candidate and hope
        self._voice = candidates[0]
        return candidates[0]

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        import edge_tts

        voice_name = voice or self._voice or await self._resolve_voice(voice)

        buf = io.BytesIO()
        communicate = edge_tts.Communicate(text, voice_name)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])

        return buf.getvalue()
