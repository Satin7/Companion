"""
ProactiveScheduler — core attention-driven proactive engine.

Runs independently of any WebSocket: periodically walks all registered
(user, contact) engine bundles, wakes via the attention rhythm, evaluates
the proactive decision, generates the message and persists it.

Keys with a connected LiveSession are skipped — live mode drives its own
scheduler and pushes over the WebSocket.

Philosophy: [[desire-system]] — desire drives decisions, not discrete rules.
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Optional

from app.deepseek_client import DeepseekClient
from app.sessions import SessionManager
from app.state_engine import (
    StateRegistry,
    CompanionEngines,
    engines_time_tick,
    life_check_for_life_signal,
    life_on_proactive_sent,
    desire_satisfy,
    emotion_check_for_signal,
    emotion_urgency_peek,
    current_follow_up_mode,
    resolve_present_follow_up_policy,
    compute_next_delay,
)
from app.trigger_engine import TriggerEngine

logger = logging.getLogger("companion.proactive")

PROACTIVE_PREFIX = "[主动关心] "
TEST_CONTACT_ID = "test"
LOOP_INTERVAL_SEC = 5.0
TEST_MODE_CANNED_MESSAGE = (
    "这是测试模式的主动消息：每 1 分钟触发一次。你可以填写 API Key 来改为 LLM 生成内容。"
)


class ProactiveScheduler:
    """Background attention scheduler for channels without a live connection."""

    def __init__(
        self,
        registry: StateRegistry,
        session_manager: SessionManager,
        deepseek: DeepseekClient,
        trigger_engine: TriggerEngine,
        live_manager,
    ):
        self._registry = registry
        self._sessions = session_manager
        self._deepseek = deepseek
        self._engine = trigger_engine
        self._live = live_manager
        self._task: Optional[asyncio.Task] = None
        self._next_check: dict[str, float] = {}  # key -> unix ts of next attention tick

    # ── lifecycle ──

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._loop())
            logger.info("proactive scheduler started")

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None

    def wake(self, user_id: str, contact_id: str) -> None:
        """Recompute the next check after an external event (user message, mode switch)."""
        engines = self._registry.get(user_id, contact_id)
        if not engines:
            return
        key = StateRegistry._key(user_id, contact_id)
        now = time.time()
        idle_ms = (now - engines.life.last_interaction_ts) * 1000
        delay_ms = compute_next_delay(
            idle_ms,
            engines.life.interaction_mode,
            emotion_urgency_peek(engines.emotion),
            current_follow_up_mode(engines),
            test_mode=(contact_id == TEST_CONTACT_ID),
        )
        self._next_check[key] = now + delay_ms / 1000.0

    async def on_user_present(self, user_id: str, contact_id: str, source: str = "manual") -> dict | None:
        """Unified entry point for "user is present" events.

        *source* identifies the trigger:
          - ``"manual"`` — user switched interaction mode to PRESENT
          - ``"visual"`` — camera / vision system detected the user

        All sources share the same flow: entry_burst → evaluate → greet if warranted.
        """
        engines = self._registry.get(user_id, contact_id)
        if not engines:
            return None

        from app.state_engine import desire_entry_burst
        desire_entry_burst(engines.desire)

        key = StateRegistry._key(user_id, contact_id)
        now = time.time()

        hints = {
            "manual": "用户手动切换到在场模式，可以打个招呼",
            "visual": "摄像头识别到用户出现，可以自然地打个招呼",
        }
        life_event = {
            "reason": f"USER_PRESENT_{source.upper()}",
            "idle_minutes": int((now - engines.life.last_interaction_ts) / 60),
            "context_hint": hints.get(source, "用户出现了"),
        }
        emotion_event = emotion_check_for_signal(engines.emotion)
        decision = await self._evaluate_and_maybe_send(
            user_id, contact_id, engines,
            life_event=life_event, emotion_event=emotion_event,
            test_mode=(contact_id == TEST_CONTACT_ID),
        )
        if decision:
            self._next_check[key] = now  # next loop tick picks up updated state
        return decision

    # ── main loop ──

    async def _loop(self):
        while True:
            try:
                await asyncio.sleep(LOOP_INTERVAL_SEC)
                await self._tick_all()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("proactive scheduler iteration failed")

    async def _tick_all(self):
        now = time.time()
        for key, engines in self._registry.items():
            try:
                user_id, contact_id = key.split("::", 1)
                live = self._live.get(user_id, contact_id)
                if live and live.connected:
                    continue  # live session drives its own scheduler
                if now < self._next_check.get(key, 0.0):
                    continue
                await self._tick_key(user_id, contact_id, engines, now)
            except Exception:
                logger.exception("proactive tick failed key=%s", key)

    async def _tick_key(self, user_id: str, contact_id: str, engines: CompanionEngines, now: float):
        key = StateRegistry._key(user_id, contact_id)
        test_mode = contact_id == TEST_CONTACT_ID
        if test_mode:
            engines.life.idle_threshold_ms = 60_000  # 1 minute
            if engines.life.last_proactive_sent_ts <= 0:
                # Anchor the 1-minute clock on first tick (mirrors the old
                # frontend's enableTestMode) — otherwise `due` never fires.
                engines.life.last_proactive_sent_ts = now

        # Passive time advance (delta-based desire accumulation)
        engines_time_tick(engines, now)

        # Schedule the next check first so failures never hot-loop
        idle_ms = (now - engines.life.last_interaction_ts) * 1000
        urgency = emotion_urgency_peek(engines.emotion)
        follow_up = current_follow_up_mode(engines)
        delay_ms = compute_next_delay(
            idle_ms, engines.life.interaction_mode, urgency, follow_up, test_mode=test_mode
        )
        self._next_check[key] = now + delay_ms / 1000.0

        # Decide whether this tick should evaluate proactive speech.
        # Attention rhythm woke us; evaluation itself is gated by a cheap local
        # desire check so we only pay the LLM decision call when speech is plausible.
        life_event = life_check_for_life_signal(engines.life, now)
        if engines.life.interaction_mode == "PRESENT":
            min_desire = resolve_present_follow_up_policy(
                engines.life.last_user_msg_signal, engines.desire.desire_level
            )["threshold"]
        else:
            min_desire = 0.5
        desire_driven = engines.desire.desire_level >= min_desire
        if not (life_event or test_mode or desire_driven):
            return

        emotion_event = emotion_check_for_signal(engines.emotion)
        decision = await self._evaluate_and_maybe_send(
            user_id, contact_id, engines,
            life_event=life_event, emotion_event=emotion_event, test_mode=test_mode,
        )
        # Desire-driven evaluation that ended in silence: decay desire so the
        # next evaluation backs off naturally instead of hot-looping LLM calls.
        if decision and not decision.get("should_speak") and not life_event and not test_mode:
            engines.desire.desire_level = max(0.0, engines.desire.desire_level - 0.12)

    # ── post-reply evaluation (PRESENT follow-up, mirrors old evaluatePostReply) ──

    async def evaluate_post_reply(self, user_id: str, contact_id: str) -> None:
        engines = self._registry.get(user_id, contact_id)
        if not engines or engines.life.interaction_mode != "PRESENT":
            return
        live = self._live.get(user_id, contact_id)
        if live and live.connected:
            return  # live session handles its own follow-up
        life_event = {
            "reason": "PRESENT_FOLLOW_UP",
            "idle_minutes": 0,
            "context_hint": "用户刚发完消息，在场承接",
            "user_msg_signal": engines.life.last_user_msg_signal,
        }
        emotion_event = emotion_check_for_signal(engines.emotion)
        decision = await self._evaluate_and_maybe_send(
            user_id, contact_id, engines,
            life_event=life_event, emotion_event=emotion_event,
            test_mode=(contact_id == TEST_CONTACT_ID),
        )
        if decision and not decision.get("should_speak"):
            # No follow-up — decay desire slightly (mirrors old frontend)
            engines.desire.desire_level = max(0.0, engines.desire.desire_level - 0.12)

    # ── decision + generation ──

    async def _evaluate_and_maybe_send(
        self,
        user_id: str,
        contact_id: str,
        engines: CompanionEngines,
        life_event: Optional[dict] = None,
        emotion_event: Optional[dict] = None,
        test_mode: bool = False,
    ) -> Optional[dict]:
        from app.models import (
            ProactiveDecisionRequest,
            LifeEvent as LifeEventModel,
            EmotionEvent as EmotionEventModel,
            ConversationMessage,
        )

        session_id = self._sessions.get_or_create_session(user_id, contact_id=contact_id)
        history = self._sessions.get_context(session_id, limit=8)
        messages = [
            ConversationMessage(role=m.get("role", "user"), content=m.get("content", ""))
            for m in history
        ]

        le = None
        if life_event:
            le = LifeEventModel(
                reason=life_event.get("reason", ""),
                idle_minutes=life_event.get("idle_minutes"),
                context_hint=life_event.get("context_hint"),
                user_msg_signal=life_event.get("user_msg_signal"),
            )
        ee = None
        if emotion_event:
            ee = EmotionEventModel(
                reason=emotion_event.get("reason", ""),
                urgency=float(emotion_event.get("urgency", 0)),
                valence=emotion_event.get("valence"),
                arousal=emotion_event.get("arousal"),
            )

        req = ProactiveDecisionRequest(
            user_id=user_id,
            interaction_mode=engines.life.interaction_mode,
            desire_level=engines.desire.desire_level,
            consecutive_no_reply=engines.life.consecutive_no_reply,
            test_mode=test_mode,
            now_ts_ms=int(time.time() * 1000),
            last_proactive_sent_ms=int(engines.life.last_proactive_sent_ts * 1000) or None,
            messages=messages,
            life_event=le,
            emotion_event=ee,
        )

        api_key = self._deepseek.api_key or None
        if not api_key:
            logger.warning("no API key for proactive — set DEEPSEEK_API_KEY env var (user=%s)", user_id)
            return None

        try:
            result = await self._engine.decide_proactive(req, api_key_override=api_key)
        except Exception:
            logger.exception("decide_proactive failed user=%s contact=%s", user_id, contact_id)
            return None

        decision = {
            "should_speak": result.should_speak,
            "topic_hint": result.topic_hint,
            "confidence": result.confidence,
            "strategy": result.strategy,
            "follow_up_mode": result.follow_up_mode,
        }
        engines.last_decision = {
            "at": time.time(),
            **decision,
            "factors": {
                "desire": f"{engines.desire.desire_level:.2f}",
                "mode": engines.life.interaction_mode,
                "emotion_state": engines.emotion.state,
                "life_state": engines.life.state,
            },
        }
        logger.info(
            "proactive decision user=%s contact=%s speak=%s strategy=%s follow_up=%s desire=%.2f",
            user_id, contact_id, decision["should_speak"], decision["strategy"],
            decision["follow_up_mode"], engines.desire.desire_level,
        )

        if not decision["should_speak"]:
            return decision

        msg = await self._generate(user_id, contact_id, engines, session_id, decision, api_key, test_mode)
        if msg:
            now = time.time()
            life_on_proactive_sent(engines.life, now)
            desire_satisfy(engines.desire)
            engines.persona.mood = min(1.0, engines.persona.mood + 0.05)
            logger.info("proactive sent user=%s contact=%s strategy=%s", user_id, contact_id, decision["strategy"])
        return decision

    async def _generate(
        self,
        user_id: str,
        contact_id: str,
        engines: CompanionEngines,
        session_id: str,
        decision: dict,
        api_key: Optional[str],
        test_mode: bool,
    ) -> Optional[str]:
        # Test mode without a key: deterministic canned message
        if not api_key and test_mode:
            self._sessions.append_message(
                session_id, role="assistant", text=PROACTIVE_PREFIX + TEST_MODE_CANNED_MESSAGE
            )
            return TEST_MODE_CANNED_MESSAGE
        if not api_key:
            return None  # no key, can't generate

        from app.message_builder import MessageBuilder
        builder = MessageBuilder(self._deepseek, self._sessions)
        result = await builder.build_proactive(
            user_id, contact_id, session_id, decision, api_key,
            voice=True, interaction_mode=engines.life.interaction_mode,
        )
        return result.reply or None
