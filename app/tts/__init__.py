"""TTS (Text-to-Speech) module — pluggable provider architecture.

Add new providers by subclassing BaseTTSProvider and registering them in
``_PROVIDERS`` below.  The Core API endpoint always goes through
``get_tts_provider()`` so swapping engines is a one-line config change.

Environment variables:
  ``TTS_PROVIDER`` — which provider to use (default ``"edge"``).
    Future values: ``"openai"``, ``"indextts"``.

Usage::

    from app.tts import get_tts_provider, tts_cache
    audio_id = await tts_cache.synthesize("Hello world")
"""

import os

from app.tts.base import BaseTTSProvider
from app.tts.edge_tts_provider import EdgeTTSProvider

_PROVIDERS: dict[str, BaseTTSProvider] = {
    "edge": EdgeTTSProvider(),
}

# Lazily-initialised singleton for the TTSCache.
# Declared here so downstream callers can ``from app.tts import tts_cache``.
tts_cache = None  # type: ignore[assignment] — set by first call to get_tts_cache()


def get_tts_provider(name: str | None = None) -> BaseTTSProvider:
    """Resolve a TTS provider by name (default from ``TTS_PROVIDER`` env, else ``"edge"``)."""
    if name is None:
        name = os.getenv("TTS_PROVIDER", "edge").strip()
    provider = _PROVIDERS.get(name)
    if provider is None:
        raise ValueError(
            f"Unknown TTS provider '{name}'. Available: {', '.join(_PROVIDERS)}"
        )
    return provider


def get_tts_cache():
    """Return the singleton TTSCache (lazy init)."""
    global tts_cache
    if tts_cache is None:
        from app.tts.cache import TTSCache  # deferred import to avoid circular deps
        tts_cache = TTSCache()
    return tts_cache
