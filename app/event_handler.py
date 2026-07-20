"""
Event handler — routes WebSocket events to LiveSession methods.

Thin dispatch layer. All business logic lives in LiveSession.
"""

from __future__ import annotations
import logging
from app.live_session import LiveSession

logger = logging.getLogger("companion.events")


async def handle_event(session: LiveSession, event: dict) -> None:
    """Top-level event router. Dispatches to the appropriate LiveSession handler."""
    event_type = event.get("type", "")

    try:
        if event_type == "user.message":
            text = str(event.get("text", "") or "").strip()
            if not text:
                return
            mode = str(event.get("mode", session.life.interaction_mode) or session.life.interaction_mode)
            await session.handle_user_message(text, mode)

        elif event_type == "user.typing":
            active = bool(event.get("active", False))
            await session.handle_user_typing(active)

        elif event_type == "user.mode":
            mode = str(event.get("mode", "ABSENT") or "ABSENT").upper()
            if mode in ("PRESENT", "ABSENT"):
                await session.handle_user_mode(mode)

        elif event_type == "user.idle":
            idle_ms = int(event.get("idle_ms", 0) or 0)
            await session.handle_user_idle(idle_ms)

        elif event_type == "ping":
            await session.websocket.send_json({"type": "pong"})

        else:
            logger.debug("unknown event type: %s", event_type)

    except Exception:
        logger.exception("unhandled error processing event type=%s user=%s", event_type, session.user_id)
        try:
            await session._send({
                "type": "error",
                "code": "internal_error",
                "detail": "Failed to process event",
            })
        except Exception:
            pass
