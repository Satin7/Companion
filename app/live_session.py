"""
LiveSession — per-user, per-contact live session bound to one WebSocket.

Orchestrates: state engines, scheduler, generation, interruption.
Replaces the browser-side LifeEngine/EmotionEngine/AttentionScheduler/DecisionClient.

Philosophy: [[desire-system]] — desire drives decisions, not discrete rules.
"""

from __future__ import annotations
import asyncio
import json
import logging
import random
import time
import uuid
import httpx
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import WebSocket

from app.deepseek_client import DeepseekClient
from app.sessions import SessionManager
from app.state_engine import (
    LifeEngineState,
    EmotionEngineState,
    DesireState,
    PersonaState,
    EmotionalProfile,
    CompanionEngines,
    StateRegistry,
    engines_on_user_message,
    emotion_urgency_peek,
    current_follow_up_mode,
    follow_up_mode_from_strategy,
    life_on_user_message,
    life_on_timer_tick,
    life_on_proactive_sent,
    life_check_for_life_signal,
    life_status,
    emotion_update,
    emotion_keyword_fallback,
    emotion_check_for_signal,
    emotion_status,
    desire_accumulate,
    desire_entry_burst,
    desire_satisfy,
    desire_nudge,
    desire_status,
    attention_probability,
    compute_next_delay,
)

logger = logging.getLogger("companion.live")


# ═══════════════════════════════════════════════════════════════
# GenerationHandle — cancellation token for streaming generation
# ═══════════════════════════════════════════════════════════════

class GenerationHandle:
    """Token-level cancellation token for streaming generation."""

    def __init__(self):
        self._cancelled = asyncio.Event()

    def cancel(self):
        self._cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()


# ═══════════════════════════════════════════════════════════════
# LiveSession
# ═══════════════════════════════════════════════════════════════

class LiveSession:
    """Per-user, per-contact live session bound to one WebSocket."""

    def __init__(
        self,
        websocket: WebSocket,
        user_id: str,
        contact_id: str,
        api_key: Optional[str],
        deepseek: DeepseekClient,
        session_manager: SessionManager,
        engines: CompanionEngines,
    ):
        self.websocket = websocket
        self.user_id = user_id
        self.contact_id = contact_id
        self.api_key = api_key
        self.deepseek = deepseek
        self.session_manager = session_manager

        # SQLite session
        self.session_id = session_manager.get_or_create_session(user_id, contact_id=contact_id)

        # Shared engine states (survive reconnects; shared with normal mode)
        self._engines = engines
        self.life = engines.life
        self.emotion = engines.emotion
        self.desire = engines.desire
        self.persona = engines.persona

        # Generation control
        self.current_generation: Optional[GenerationHandle] = None
        self._gen_lock = asyncio.Lock()

        # Scheduler
        self._scheduler_task: Optional[asyncio.Task] = None
        self._scheduler_wake: asyncio.Event = asyncio.Event()
        self._connected: bool = False

        # Typing state
        self.user_typing: bool = False
        self.companion_typing: bool = False
        self._typing_cooldown_task: Optional[asyncio.Task] = None

        # Voice mode
        self.voice_mode: bool = False
        self.voice: Optional[str] = None

        # Test mode
        self.test_mode: bool = (contact_id == "test")

        if self.test_mode:
            self.life.idle_threshold_ms = 60_000  # 1 minute

    # ── connection lifecycle ──

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self):
        """Called after WebSocket accept. Loads history and starts scheduler."""
        self._connected = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        # Push initial state
        await self._push_thinking_state()

    async def stop(self):
        """Called on disconnect. Cancels scheduler and any in-progress generation."""
        self._connected = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            self._scheduler_task = None
        if self._typing_cooldown_task:
            self._typing_cooldown_task.cancel()
            self._typing_cooldown_task = None
        await self._cancel_generation()

    # ── sending helpers ──

    async def _send(self, payload: dict) -> bool:
        """Send JSON to the WebSocket. Returns False if disconnected."""
        try:
            await self.websocket.send_json(payload)
            return True
        except Exception:
            self._connected = False
            return False

    async def _push_thinking_state(self):
        """Push internal state to frontend for debug/thinking panel."""
        life_s = life_status(self.life)
        emotion_s = emotion_status(self.emotion)
        desire_s = desire_status(self.desire)
        now = time.time()
        idle_ms = (now - self.life.last_interaction_ts) * 1000
        p = attention_probability(
            idle_ms, self.life.interaction_mode,
            emotion_urgency_peek(self.emotion),
            current_follow_up_mode(self._engines),
        )
        await self._send({
            "type": "thinking.state",
            "desire": desire_s["desire"],
            "attention_p": f"{p:.3f}",
            "emotion_state": emotion_s["state"],
            "life_state": life_s["state"],
            "mode": self.life.interaction_mode,
            "idle_min": str(life_s["idleMin"]),
        })

    # ── generation control ──

    async def _cancel_generation(self):
        """Cancel any in-progress streaming generation."""
        if self.current_generation:
            self.current_generation.cancel()
            self.current_generation = None
        if self.companion_typing:
            self.companion_typing = False
            await self._send({"type": "companion.typing", "active": False})

    async def _generate_reply(self, user_text: str, mode: str):
        """Generate a chat reply for the user's message. Non-streaming in Phase 1."""
        await self._cancel_generation()

        self.companion_typing = True
        await self._send({"type": "companion.typing", "active": True})

        reply_id = f"r_{uuid.uuid4().hex[:8]}"
        await self._send({"type": "reply.start", "reply_id": reply_id, "mode": "chat"})

        # Build prompt and messages — reuses the same logic as /chat/reply
        from app.main import PERSONA_BASE_PROMPT, _load_self_profile_text, _memory_context, _is_context_free_query
        memory = self.session_manager.get_memory(self.user_id, contact_id=self.contact_id)
        self_profile_text = _load_self_profile_text()
        prompt = PERSONA_BASE_PROMPT.strip()
        if self_profile_text:
            prompt += "\n\n" + self_profile_text
        if not _is_context_free_query(user_text):
            prompt += _memory_context(memory)

        # ── Engagement contract (LLM sidecar) ──
        from app.engagement import ENGAGEMENT_CONTRACT, scan_keywords, apply_engagement
        prompt += ENGAGEMENT_CONTRACT

        # Keyword scan
        kw_eng = scan_keywords(user_text)
        if kw_eng:
            apply_engagement(self.desire, kw_eng)

        context_limit = 40
        history = self.session_manager.get_context(self.session_id, limit=context_limit)
        llm_messages = [{"role": "system", "content": prompt}] + [
            {"role": m.get("role", "user"), "content": m.get("content", "")} for m in history
        ]

        # Append the new user message (it was already persisted by handle_user_message)
        # Actually — it's NOT yet persisted since we're in the event handler flow.
        # We need to persist it here or before calling this.
        # The event_handler persists it first, so history already includes it.

        full_text = ""
        try:
            handle = GenerationHandle()
            self.current_generation = handle

            # Phase 1: non-streaming. Phase 2 will switch to chat_complete_stream.
            result = await self.deepseek.chat_complete(
                messages=llm_messages,
                max_tokens=1024,
                temperature=0.9,
                api_key=self.api_key,
            )
            full_text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

            if handle.is_cancelled:
                return  # interrupted before we could send
        except httpx.TimeoutException:
            await self._send({"type": "error", "code": "timeout", "detail": "Upstream model timeout"})
            return
        except Exception as e:
            await self._send({"type": "error", "code": "generation_failed", "detail": str(e)[:200]})
            return
        finally:
            self.current_generation = None

        if not full_text:
            await self._send({"type": "error", "code": "empty_reply", "detail": "Model returned empty reply"})
            return

        # Post-process (same pipeline as /chat/reply)
        from app.main import _normalize_reply_style, _limit_reply_length, _split_reply_segments
        processed = _normalize_reply_style(full_text)
        processed = _limit_reply_length(processed, user_text)
        segments = _split_reply_segments(processed)

        # ── Engagement: parse LLM output ──
        from app.engagement import parse_llm_engagement, apply_engagement
        llm_eng = parse_llm_engagement(processed)
        if llm_eng and llm_eng["direction"] != "neutral":
            apply_engagement(self.desire, llm_eng)

        # ── TTS voice synthesis (best-effort, per segment, before persist) ──
        audio_urls: list[str] = []
        if self.voice_mode and segments:
            try:
                from app.tts import get_tts_cache
                cache = get_tts_cache()
                for seg in segments:
                    audio_id = await cache.synthesize(seg, voice=self.voice)
                    audio_urls.append(f"/chat/audio/{audio_id}")
            except Exception:
                logger.exception("TTS synthesis failed in live session user=%s", self.user_id)

        import json as _json
        audio_url_json = _json.dumps(audio_urls, ensure_ascii=False) if audio_urls else None

        # Persist
        self.session_manager.append_message(
            self.session_id, role="assistant", text=processed,
            segments=segments, audio_url=audio_url_json,
        )

        # Memory update (async, background)
        from app.main import _update_memory_background
        asyncio.create_task(
            _update_memory_background(
                session_id=self.session_id,
                user_id=self.user_id,
                contact_id=self.contact_id,
                user_message=user_text,
                api_key=self.api_key,
            )
        )

        # Refresh memory for response
        memory = self.session_manager.get_memory(self.user_id, contact_id=self.contact_id)
        from app.models import MemoryProfile
        mem_profile = MemoryProfile(**memory)

        await self._send({
            "type": "reply.end",
            "reply_id": reply_id,
            "full_text": processed,
            "segments": segments,
            "memory": mem_profile.dict(),
            "audio_urls": audio_urls if audio_urls else None,
        })

        self.companion_typing = False
        await self._send({"type": "companion.typing", "active": False})

    async def _generate_proactive(self, decision: dict) -> Optional[str]:
        """Generate a proactive message. Returns the message text or None."""
        self.companion_typing = True
        await self._send({"type": "companion.typing", "active": True})

        reply_id = f"p_{uuid.uuid4().hex[:8]}"
        strategy = decision.get("strategy", "reduce_frequency")
        topic_hint = decision.get("topic_hint")
        await self._send({
            "type": "proactive.start",
            "reply_id": reply_id,
            "strategy": strategy,
            "topic_hint": topic_hint,
        })

        # Build proactive prompt (reuses /proactive/generate logic)
        from app.main import _build_proactive_system_prompt
        memory = self.session_manager.get_memory(self.user_id, contact_id=self.contact_id)
        mode = self.life.interaction_mode
        follow_up = decision.get("follow_up_mode", "light")
        prompt = _build_proactive_system_prompt(mode, memory, follow_up)

        # Get recent messages for context
        history = self.session_manager.get_context(self.session_id, limit=8)
        ctx_lines = ["最近的对话："]
        for m in history[-8:]:
            role_label = "用户" if m.get("role") == "user" else "AI"
            ctx_lines.append(f"{role_label}: {m.get('content', '')}")
        if topic_hint:
            ctx_lines.append(f"\n建议话题：{topic_hint}")
        ctx_lines.append("\n请生成一条主动发起的消息：")
        user_prompt = "\n".join(ctx_lines)

        full_text = ""
        try:
            handle = GenerationHandle()
            self.current_generation = handle

            result = await self.deepseek.chat_complete(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=300,
                temperature=0.9,
                api_key=self.api_key,
            )
            full_text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

            if handle.is_cancelled:
                return None
        except Exception:
            await self._send({"type": "error", "code": "proactive_failed", "detail": "Failed to generate proactive message"})
            return None
        finally:
            self.current_generation = None

        if not full_text:
            return None

        # Post-process
        from app.main import _normalize_reply_style, _limit_reply_length, _split_reply_segments
        processed = _normalize_reply_style(full_text)
        processed = _limit_reply_length(processed, "这是一条主动发起的陪伴消息")
        segments = _split_reply_segments(processed)

        # ── TTS voice synthesis (best-effort, per segment, before persist) ──
        audio_urls: list[str] = []
        if self.voice_mode and segments:
            try:
                from app.tts import get_tts_cache
                cache = get_tts_cache()
                for seg in segments:
                    audio_id = await cache.synthesize(seg, voice=self.voice)
                    audio_urls.append(f"/chat/audio/{audio_id}")
            except Exception:
                logger.exception("TTS synthesis failed in live proactive user=%s", self.user_id)

        import json as _json
        audio_url_json = _json.dumps(audio_urls, ensure_ascii=False) if audio_urls else None

        # Persist (with the proactive marker so history sync renders it as proactive)
        from app.proactive_scheduler import PROACTIVE_PREFIX
        self.session_manager.append_message(
            self.session_id, role="assistant",
            text=PROACTIVE_PREFIX + processed,
            segments=segments, audio_url=audio_url_json,
        )

        await self._send({
            "type": "proactive.end",
            "reply_id": reply_id,
            "full_text": processed,
            "segments": segments,
            "audio_urls": audio_urls if audio_urls else None,
        })

        self.companion_typing = False
        await self._send({"type": "companion.typing", "active": False})
        return processed

    # ── decision ──

    async def _decide_proactive(self, life_event: Optional[dict] = None, emotion_event: Optional[dict] = None) -> dict:
        """Decide whether Companion should speak proactively."""
        from app.models import (
            ProactiveDecisionRequest,
            LifeEvent as LifeEventModel,
            EmotionEvent as EmotionEventModel,
            ConversationMessage,
        )
        from app.trigger_engine import TriggerEngine

        # Get recent messages
        history = self.session_manager.get_context(self.session_id, limit=8)
        messages = [ConversationMessage(role=m.get("role", "user"), content=m.get("content", "")) for m in history]

        # Build LifeEvent model
        le = None
        if life_event:
            le = LifeEventModel(
                reason=life_event.get("reason", ""),
                idle_minutes=life_event.get("idle_minutes"),
                context_hint=life_event.get("context_hint"),
                user_msg_signal=life_event.get("user_msg_signal"),
            )

        # Build EmotionEvent model
        ee = None
        if emotion_event:
            ee = EmotionEventModel(
                reason=emotion_event.get("reason", ""),
                urgency=float(emotion_event.get("urgency", 0)),
                valence=emotion_event.get("valence"),
                arousal=emotion_event.get("arousal"),
            )

        req = ProactiveDecisionRequest(
            user_id=self.user_id,
            interaction_mode=self.life.interaction_mode,
            desire_level=self.desire.desire_level,
            consecutive_no_reply=self.life.consecutive_no_reply,
            test_mode=self.test_mode,
            now_ts_ms=int(time.time() * 1000),
            last_proactive_sent_ms=int(self.life.last_proactive_sent_ts * 1000) if self.life.last_proactive_sent_ts else None,
            messages=messages,
            life_event=le,
            emotion_event=ee,
        )

        # Reuse TriggerEngine's decision logic
        # We create a lightweight instance just for the decision call
        from app.trigger_engine import TriggerEngine
        temp_engine = TriggerEngine(deepseek_client=self.deepseek, session_manager=self.session_manager)
        result = await temp_engine.decide_proactive(req, api_key_override=self.api_key)

        decision = {
            "should_speak": result.should_speak,
            "topic_hint": result.topic_hint,
            "confidence": result.confidence,
            "strategy": result.strategy,
            "follow_up_mode": result.follow_up_mode,
        }

        # Record + push thinking decision
        self._engines.last_decision = {
            "at": time.time(),
            "strategy": result.strategy,
            "should_speak": result.should_speak,
            "confidence": result.confidence,
            "topic_hint": result.topic_hint,
            "follow_up_mode": result.follow_up_mode,
            "factors": {
                "desire": f"{self.desire.desire_level:.2f}",
                "mode": self.life.interaction_mode,
                "emotion_state": self.emotion.state,
                "life_state": self.life.state,
            },
        }
        await self._send({
            "type": "thinking.decision",
            "strategy": result.strategy,
            "should_speak": result.should_speak,
            "confidence": result.confidence,
            "topic_hint": result.topic_hint,
            "follow_up_mode": result.follow_up_mode,
            "factors": self._engines.last_decision["factors"],
        })

        return decision

    # ── scheduler ──

    async def _scheduler_loop(self):
        """Background task: evaluate attention rhythm and decide whether to speak."""
        while self._connected:
            try:
                # Sleep for computed delay, but wake on events
                delay_ms = compute_next_delay(
                    idle_ms=(time.time() - self.life.last_interaction_ts) * 1000,
                    mode=self.life.interaction_mode,
                    emotion_urgency=emotion_urgency_peek(self.emotion),
                    follow_up_mode=current_follow_up_mode(self._engines),
                    test_mode=self.test_mode,
                )
                delay_sec = delay_ms / 1000.0

                try:
                    # Wake either on timeout or on event signal
                    await asyncio.wait_for(self._scheduler_wake.wait(), timeout=max(1.0, delay_sec))
                    self._scheduler_wake.clear()
                except asyncio.TimeoutError:
                    pass  # Normal timeout — time for a scheduler tick

                if not self._connected:
                    break

                await self._attention_tick()
            except asyncio.CancelledError:
                break

    async def _attention_tick(self):
        """One scheduler tick: evaluate state and decide whether to speak proactively."""
        now = time.time()

        # 1. Advance LifeEngine with time
        life_on_timer_tick(self.life, now)

        # 2. Accumulate desire
        idle_min = max(0.5, (now - self.life.last_interaction_ts) / 60.0)
        emotion_event = emotion_check_for_signal(self.emotion)
        urgency = emotion_event.get("urgency", 0) if emotion_event else 0
        desire_accumulate(self.desire, idle_min, urgency)

        # 3. Check for life signal
        life_event = life_check_for_life_signal(self.life, now)

        # 4. If there's a life signal, or in PRESENT mode, evaluate proactive
        if life_event or self.life.interaction_mode == "PRESENT":
            # In PRESENT mode, only evaluate if user is not typing
            if self.user_typing:
                return

            decision = await self._decide_proactive(life_event, emotion_event)

            if decision.get("should_speak"):
                msg = await self._generate_proactive(decision)
                if msg:
                    life_on_proactive_sent(self.life, now)
                    desire_satisfy(self.desire)
                    self.persona.mood = min(1.0, self.persona.mood + 0.05)
                    logger.info(
                        "proactive sent user=%s contact=%s strategy=%s desire=%.2f",
                        self.user_id, self.contact_id,
                        decision.get("strategy"), self.desire.desire_level,
                    )
            else:
                # Push a visible skip notice so user knows the scheduler ran but chose silence
                await self._send({
                    "type": "thinking.skipped",
                    "reason": "attention_tick",
                    "desire": f"{self.desire.desire_level:.2f}",
                    "strategy": decision.get("strategy", ""),
                    "confidence": decision.get("confidence", 0),
                })

        # 5. Push state update
        await self._push_thinking_state()

    def _wake_scheduler(self):
        """Signal the scheduler to re-evaluate immediately."""
        self._scheduler_wake.set()

    # ── event handlers (called by event_handler.py) ──

    async def handle_user_message(self, text: str, mode: str):
        """User sent a message."""
        now = time.time()

        # Cancel any in-progress generation
        await self._cancel_generation()

        # Persist user message
        self.session_manager.append_message(self.session_id, role="user", text=text)

        # Update shared engines (life + desire + emotion via keyword VAD)
        recent = self.session_manager.get_context(self.session_id, limit=12)
        engines_on_user_message(self._engines, now, text, recent)

        # Generate reply
        await self._generate_reply(text, mode)

        # After reply, evaluate proactive follow-up in PRESENT mode
        if self.life.interaction_mode == "PRESENT" and not self.user_typing:
            emotion_event = emotion_check_for_signal(self.emotion)
            decision = await self._decide_proactive(
                life_event={
                    "reason": "PRESENT_FOLLOW_UP",
                    "idle_minutes": 0,
                    "context_hint": "用户刚发完消息，在场承接",
                    "user_msg_signal": self.life.last_user_msg_signal,
                },
                emotion_event=emotion_event,
            )
            if decision.get("should_speak"):
                msg = await self._generate_proactive(decision)
                if msg:
                    life_on_proactive_sent(self.life, now)
                    desire_satisfy(self.desire)
                    self.persona.mood = min(1.0, self.persona.mood + 0.05)
            else:
                # No proactive message — decay desire slightly
                self.desire.desire_level = max(0.0, self.desire.desire_level - 0.12)
                await self._send({
                    "type": "thinking.skipped",
                    "reason": "post_reply",
                    "desire": f"{self.desire.desire_level:.2f}",
                    "strategy": decision.get("strategy", ""),
                    "confidence": decision.get("confidence", 0),
                })

        # Wake scheduler to reset its timer
        self._wake_scheduler()
        await self._push_thinking_state()

    async def handle_user_typing(self, active: bool):
        """User started or stopped typing."""
        self.user_typing = active

        if not active:
            # User stopped typing — start cooldown before proactive evaluation
            if self._typing_cooldown_task:
                self._typing_cooldown_task.cancel()
            self._typing_cooldown_task = asyncio.create_task(self._typing_cooldown())
        else:
            # User is typing — cancel any pending cooldown
            if self._typing_cooldown_task:
                self._typing_cooldown_task.cancel()
                self._typing_cooldown_task = None

    async def _typing_cooldown(self):
        """After user stops typing, wait 2s then evaluate if Companion should speak."""
        await asyncio.sleep(2.0)
        if not self._connected or self.user_typing:
            return
        # Evaluate proactive in PRESENT mode
        if self.life.interaction_mode == "PRESENT":
            self._wake_scheduler()

    async def handle_user_mode(self, mode: str):
        """User switched interaction mode."""
        old_mode = self.life.interaction_mode
        self.life.interaction_mode = mode

        if mode == "PRESENT" and old_mode != "PRESENT":
            desire_entry_burst(self.desire)
            logger.info("mode switch → PRESENT user=%s desire=%.2f", self.user_id, self.desire.desire_level)

        self._wake_scheduler()
        await self._push_thinking_state()

    async def handle_user_idle(self, idle_ms: int):
        """Client reports user idle time."""
        # We use this as a proxy for last_interaction_ts when user hasn't sent messages
        # but is clearly away (blur event / long idle)
        if idle_ms > 0:
            proxy_ts = time.time() - (idle_ms / 1000.0)
            if proxy_ts > self.life.last_interaction_ts:
                # Only move forward; don't rewind
                pass  # Keep actual message timestamps authoritative
        self._wake_scheduler()


# ═══════════════════════════════════════════════════════════════
# LiveSessionManager
# ═══════════════════════════════════════════════════════════════

class LiveSessionManager:
    """Manages all LiveSession instances. Replaces TriggerEngine.connections."""

    def __init__(self, state_registry: StateRegistry):
        self._sessions: Dict[str, LiveSession] = {}  # keyed by "{user_id}::{contact_id}"
        self._registry = state_registry

    def _key(self, user_id: str, contact_id: str) -> str:
        return f"{user_id}::{contact_id}"

    async def create(
        self,
        websocket: WebSocket,
        user_id: str,
        contact_id: str,
        api_key: Optional[str],
        deepseek: DeepseekClient,
        session_manager: SessionManager,
    ) -> LiveSession:
        """Create and register a new LiveSession."""
        key = self._key(user_id, contact_id)
        # If an existing session is still connected, close it
        existing = self._sessions.get(key)
        if existing and existing.connected:
            await existing.stop()
        engines = self._registry.get_or_create(user_id, contact_id)
        if api_key:
            engines.api_key = api_key  # share the key with the core scheduler
        session = LiveSession(websocket, user_id, contact_id, api_key, deepseek, session_manager, engines)
        self._sessions[key] = session
        return session

    async def remove(self, user_id: str, contact_id: str):
        """Remove and stop a LiveSession."""
        key = self._key(user_id, contact_id)
        session = self._sessions.pop(key, None)
        if session:
            await session.stop()

    def get(self, user_id: str, contact_id: str) -> Optional[LiveSession]:
        return self._sessions.get(self._key(user_id, contact_id))
