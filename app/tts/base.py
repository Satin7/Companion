"""Abstract base for TTS providers."""

from abc import ABC, abstractmethod


class BaseTTSProvider(ABC):
    """Every TTS engine must implement ``synthesize()`` returning MP3 bytes."""

    @abstractmethod
    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        """Convert *text* to speech and return ``audio/mpeg`` bytes."""
        ...
