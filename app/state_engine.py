"""
Companion state engines — migrated from web-shell/index.html JavaScript.

Pure data classes + pure functions. No LLM calls, no I/O.
Deterministic, testable, and driven by events from LiveSession.

Philosophy: [[desire-system]] — Companion is driven by inner desire, not discrete rules.
"""

from __future__ import annotations
import time
import math
from dataclasses import dataclass, field
from typing import Optional, Literal


# ═══════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════

@dataclass
class EmotionalProfile:
    """VAD sentiment snapshot."""
    valence: float = 0.0       # -1.0 to 1.0
    arousal: float = 0.5       # 0.0 to 1.0
    dominance: float = 0.5     # 0.0 to 1.0
    key_themes: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def is_negative(self) -> bool:
        return self.valence < -0.2

    def is_highly_aroused(self) -> bool:
        return self.arousal > 0.7

    @classmethod
    def neutral(cls) -> "EmotionalProfile":
        return cls(valence=0.0, arousal=0.5, dominance=0.5, key_themes=[])


@dataclass
class LifeEngineState:
    """Companion's sense of the user's world — idle, active hours, life signals."""
    state: Literal["IDLE", "OBSERVING", "READY"] = "IDLE"
    interaction_mode: Literal["PRESENT", "ABSENT"] = "ABSENT"
    last_interaction_ts: float = field(default_factory=time.time)
    last_proactive_sent_ts: float = 0.0
    consecutive_no_reply: int = 0
    interaction_count: int = 0
    idle_threshold_ms: int = 2 * 60 * 60 * 1000  # 2 hours
    active_hours: set[int] = field(default_factory=set)
    hist_avg: float = 10.0
    last_user_msg_signal: Optional[dict] = None  # {intensity, depth, needCare, hasQuestion, textLength}
    initial_greeting_sent: bool = False
    morning_check_sent_date: str = ""
    last_life_signal_ms: float = 0.0
    life_signal_cooldown_ms: int = 30 * 60 * 1000  # 30 min


@dataclass
class EmotionEngineState:
    """Companion's emotional perception — VAD tracking and derailment state machine."""
    state: Literal["NEUTRAL", "HEIGHTENED", "DISTRESSED"] = "NEUTRAL"
    baseline_valence: float = 0.0
    baseline_arousal: float = 0.5
    baseline_dominance: float = 0.5
    baseline_themes: list[str] = field(default_factory=list)
    current_valence: float = 0.0
    current_arousal: float = 0.5
    current_dominance: float = 0.5
    derailment: int = 0
    neg_weight: float = 0.0
    last_hash: str = ""


@dataclass
class DesireState:
    """Companion's inner connection desire — the core driver per [[desire-system]]."""
    desire_level: float = 0.0        # 0..1
    desire_base_rate: float = 0.05   # per minute
    desire_multiplier: float = 1.0


@dataclass
class PersonaState:
    """Companion's personality traits."""
    energy: float = 0.7
    mood: float = 0.7
    curiosity: int = 3
    care: int = 3
    sharing: int = 3
    memory_trait: int = 3
    openness: float = 0.5
    emotional_resonance: float = 0.5

    def motivation(self) -> int:
        return self.curiosity + self.care + self.sharing + self.memory_trait

    def is_receptive(self) -> bool:
        return self.energy > 0.4 and self.mood > 0.3


# ═══════════════════════════════════════════════════════════════
# Keyword lists (mirrored from JS exactly)
# ═══════════════════════════════════════════════════════════════

_NEED_CARE_WORDS = [
    "累", "难", "烦", "焦虑", "压力", "不开心", "难过", "崩溃",
    "失眠", "害怕", "孤独", "担心", "不舒服", "生病", "失败",
    "被拒", "分手", "迷茫", "空虚",
]

_INTENSITY_WORDS = [
    "太", "非常", "很", "特别", "急", "快", "一直", "总是",
    "真的", "超级", "好", "极",
]

_QUESTION_WORDS = [
    "?", "？", "吗", "呢", "吧", "怎么", "什么", "能不能", "要不要", "可以吗",
]

_NEGATIVE_KEYWORDS = [
    "担心", "累", "难", "烦", "焦虑", "压力", "不开心", "难过",
    "生气", "崩溃", "失眠", "害怕", "无聊", "孤独",
]


# ═══════════════════════════════════════════════════════════════
# LifeEngine pure functions
# ═══════════════════════════════════════════════════════════════

def life_analyze_message(text: str) -> dict:
    """Keyword-based message analysis. Deterministic, no LLM."""
    need_care = sum(1 for w in _NEED_CARE_WORDS if w in text)
    intensity = sum(1 for w in _INTENSITY_WORDS if w in text)
    has_question = any(w in text for w in _QUESTION_WORDS)
    depth = min(1.0, len(text) / 100.0)

    return {
        "intensity": min(1.0, intensity * 0.3),
        "depth": depth,
        "needCare": min(1.0, need_care * 0.4),
        "hasQuestion": has_question,
        "textLength": len(text),
    }


def _today_key(now_ts: float) -> str:
    """YYYY-MM-DD key for date-based latches."""
    import datetime
    dt = datetime.datetime.fromtimestamp(now_ts)
    return dt.strftime("%Y-%m-%d")


def life_on_user_message(state: LifeEngineState, now_ts: float, msg_text: str) -> None:
    """Drive source 2: user message. Mutates state in place."""
    state.last_interaction_ts = now_ts
    state.interaction_count += 1
    state.hist_avg = round((state.hist_avg * 4 + state.interaction_count) / 5)
    import datetime
    state.active_hours.add(datetime.datetime.fromtimestamp(now_ts).hour)
    state.consecutive_no_reply = 0

    if state.state == "IDLE":
        state.state = "OBSERVING"
    elif state.state == "READY":
        state.state = "OBSERVING"

    if msg_text:
        state.last_user_msg_signal = life_analyze_message(msg_text)


def life_on_timer_tick(state: LifeEngineState, now_ts: float) -> None:
    """Drive source 1: time. Checks if idle crosses threshold to become READY."""
    if state.state == "READY":
        return

    idle_ms = (now_ts - state.last_interaction_ts) * 1000
    import datetime
    current_hour = datetime.datetime.fromtimestamp(now_ts).hour
    in_window = len(state.active_hours) == 0 or current_hour in state.active_hours
    today = _today_key(now_ts)

    morning = (
        current_hour >= 10
        and state.interaction_count == 0
        and state.morning_check_sent_date != today
    )
    initial = (
        not state.initial_greeting_sent
        and state.interaction_count == 0
        and idle_ms > state.idle_threshold_ms
    )

    if morning:
        state.state = "READY"
    elif initial:
        state.state = "READY"
    elif idle_ms > state.idle_threshold_ms and in_window:
        state.state = "READY"


def life_on_proactive_sent(state: LifeEngineState, now_ts: float) -> None:
    """Record that Companion sent a proactive message."""
    state.last_proactive_sent_ts = now_ts
    state.consecutive_no_reply += 1


def life_check_for_life_signal(state: LifeEngineState, now_ts: float) -> Optional[dict]:
    """Unified output. Returns a LifeEngineEvent dict or None."""
    if state.state != "READY":
        return None
    if state.last_life_signal_ms > 0 and (now_ts * 1000 - state.last_life_signal_ms) < state.life_signal_cooldown_ms:
        return None

    idle_min = int((now_ts - state.last_interaction_ts) / 60)
    import datetime
    current_hour = datetime.datetime.fromtimestamp(now_ts).hour

    if state.interaction_count == 0 and idle_min > 0:
        reason = "INITIAL_GREETING"
        hint = "全新联系人，发起首次问候"
        state.initial_greeting_sent = True
    elif state.interaction_count == 0 and current_hour >= 10:
        reason = "MORNING_CHECK_IN"
        hint = "用户今天还没有聊天"
        state.morning_check_sent_date = _today_key(now_ts)
    else:
        reason = "PROLONGED_IDLE"
        hint = f"用户空闲 {idle_min} 分钟"

    state.state = "OBSERVING"
    state.last_life_signal_ms = now_ts * 1000

    return {
        "reason": reason,
        "confidence": min(0.95, idle_min / 480.0),
        "context_hint": hint,
        "idle_minutes": idle_min,
        "user_msg_signal": dict(state.last_user_msg_signal) if state.last_user_msg_signal else None,
    }


def life_status(state: LifeEngineState) -> dict:
    now = time.time()
    return {
        "state": state.state,
        "mode": state.interaction_mode,
        "idleMin": int((now - state.last_interaction_ts) / 60),
        "thresholdMin": int(state.idle_threshold_ms / 60000),
        "interactions": state.interaction_count,
        "noReply": state.consecutive_no_reply,
        "lastMsg": state.last_user_msg_signal,
    }


# ═══════════════════════════════════════════════════════════════
# EmotionEngine pure functions
# ═══════════════════════════════════════════════════════════════

def emotion_update(state: EmotionEngineState, profile: EmotionalProfile) -> None:
    """Apply VAD profile, update baseline EMA, detect state transitions."""
    state.current_valence = profile.valence
    state.current_arousal = profile.arousal
    state.current_dominance = profile.dominance

    # EMA update baseline
    state.baseline_valence = state.baseline_valence * 0.9 + profile.valence * 0.1
    state.baseline_arousal = state.baseline_arousal * 0.9 + profile.arousal * 0.1
    state.baseline_dominance = state.baseline_dominance * 0.9 + profile.dominance * 0.1
    # key_themes stay with baseline, not overwritten by current

    shift = profile.valence - state.baseline_valence

    # Derailment state machine
    if state.state == "NEUTRAL" and (shift < -0.3 or profile.is_highly_aroused()):
        state.state = "HEIGHTENED"
        state.derailment = 1
    elif state.state == "HEIGHTENED":
        if shift < -0.15:
            state.derailment += 1
            if state.derailment >= 3:
                state.state = "DISTRESSED"
        elif shift > -0.05:
            state.derailment = max(0, state.derailment - 1)
            if state.derailment == 0:
                state.state = "NEUTRAL"
    elif state.state == "DISTRESSED":
        if shift > -0.1:
            state.derailment = max(0, state.derailment - 1)
            if state.derailment <= 1:
                state.state = "HEIGHTENED"

    # Compute negWeight
    w = 0.0
    if profile.valence < -0.3:
        w += 0.3
    if profile.valence < -0.6:
        w += 0.3
    if profile.arousal > 0.7:
        w += 0.2
    if profile.dominance < 0.3:
        w += 0.2
    state.neg_weight = min(1.0, w)


def emotion_keyword_fallback(messages: list[dict]) -> EmotionalProfile:
    """Keyword-based fallback when LLM VAD analysis fails."""
    score = 0.0
    themes: list[str] = []
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        for w in _NEGATIVE_KEYWORDS:
            if w in content:
                score += 0.15
                if w not in themes:
                    themes.append(w)
    return EmotionalProfile(
        valence=max(-1.0, -score),
        arousal=min(1.0, score * 1.5),
        dominance=0.5,
        key_themes=themes,
    )


def emotion_check_for_signal(state: EmotionEngineState) -> Optional[dict]:
    """Check if an emotional signal should be emitted. Returns event dict or None."""
    reason = None
    urgency = 0.0

    if state.state == "DISTRESSED":
        urgency = min(1.0, 0.6 + state.derailment * 0.1)
        reason = "SUSTAINED_DISTRESS"
    elif state.state == "HEIGHTENED":
        urgency = 0.4 + state.neg_weight * 0.3
        reason = "HIGH_AROUSAL" if state.current_arousal > 0.7 else "NEGATIVE_SHIFT"

    if reason and urgency > 0.35:
        state.derailment = max(0, state.derailment - 1)
        return {
            "reason": reason,
            "urgency": urgency,
            "valence": state.current_valence,
            "arousal": state.current_arousal,
        }
    return None


def emotion_status(state: EmotionEngineState) -> dict:
    return {
        "state": state.state,
        "valence": f"{state.current_valence:.2f}",
        "arousal": f"{state.current_arousal:.2f}",
        "baselineVal": f"{state.baseline_valence:.2f}",
        "derailment": state.derailment,
        "negWeight": f"{state.neg_weight:.2f}",
    }


# ═══════════════════════════════════════════════════════════════
# DesireSystem pure functions  ([[desire-system]])
# ═══════════════════════════════════════════════════════════════

def desire_accumulate(state: DesireState, idle_minutes: float, emotion_urgency: float) -> None:
    """Called every scheduler tick. Accumulate desire based on idle time and emotional state."""
    gain = idle_minutes * state.desire_base_rate * state.desire_multiplier
    state.desire_level = min(1.0, state.desire_level + gain)

    if emotion_urgency > 0.3:
        state.desire_multiplier = 1.0 + emotion_urgency * 1.5
    else:
        state.desire_multiplier = max(0.5, state.desire_multiplier - 0.05)


def desire_entry_burst(state: DesireState) -> None:
    """User entering PRESENT mode: Companion has accumulated things to say."""
    state.desire_level = min(1.0, state.desire_level + 0.35)


def desire_satisfy(state: DesireState) -> None:
    """User interaction or proactive message satisfies desire (mild decay)."""
    state.desire_level = max(0.0, state.desire_level - 0.2)
    state.desire_multiplier = 1.0


def desire_nudge(state: DesireState, user_msg_signal: Optional[dict]) -> None:
    """User message content can nudge desire up."""
    if not user_msg_signal:
        return
    if user_msg_signal.get("needCare", 0) > 0.3:
        state.desire_level += 0.1
    if user_msg_signal.get("hasQuestion", False):
        state.desire_level += 0.05


def desire_status(state: DesireState) -> dict:
    return {
        "desire": f"{state.desire_level:.2f}",
        "rate": f"{state.desire_base_rate:.3f}",
        "multiplier": f"{state.desire_multiplier:.2f}",
    }


# ═══════════════════════════════════════════════════════════════
# Attention scheduler pure functions
# ═══════════════════════════════════════════════════════════════

SHORT_WAVE_MS = 25 * 60 * 1000   # 25 min
LONG_WAVE_MS = 90 * 60 * 1000    # 90 min
MIN_CHECK_MS = 15 * 1000         # min 15s
MAX_CHECK_MS = 20 * 60 * 1000    # max 20min
T50_MS = 2 * 60 * 60 * 1000      # idle time for P=0.5

# To keep pure functions pure, we accept a seed or use a simple deterministic
# substitute. LiveSession will add actual random jitter at call time.
def attention_probability(
    idle_ms: float,
    mode: str,
    emotion_urgency: float = 0.0,
    follow_up_mode: str = "light",
    noise: float = 0.0,  # caller provides random jitter
) -> float:
    """How likely Companion is 'thinking of' the user right now."""
    if idle_ms <= 0:
        return 0.01

    # Sigmoid base: rises with idle time
    sigmoid = 1.0 / (1.0 + math.exp(-(idle_ms - T50_MS) / (T50_MS / 4)))

    # Dual-wave fluctuation
    short_wave = math.sin(2 * math.pi * idle_ms / SHORT_WAVE_MS) * 0.08
    long_wave = math.sin(2 * math.pi * idle_ms / LONG_WAVE_MS) * 0.12

    mode_factor = 1.15 if (mode == "PRESENT" and follow_up_mode == "deepen") else 1.0
    emotion_boost = 1.0 + emotion_urgency * 0.5

    p = (sigmoid + short_wave + long_wave) * mode_factor * emotion_boost
    p += noise  # caller provides ±5% random jitter
    return max(0.01, min(0.95, p))


def compute_next_delay(
    idle_ms: float,
    mode: str,
    emotion_urgency: float = 0.0,
    follow_up_mode: str = "light",
    noise: float = 0.0,
    test_mode: bool = False,
) -> float:
    """How long to wait (ms) before next attention check."""
    if test_mode:
        return 10_000  # 10 seconds in test mode

    p = attention_probability(idle_ms, mode, emotion_urgency, follow_up_mode, noise)
    # Map P from [0.01, 0.95] to [MAX_CHECK, MIN_CHECK] using log scale
    log_p = math.log(p + 0.001)
    log_min = math.log(0.01)
    log_max = math.log(0.95)
    frac = (log_p - log_min) / (log_max - log_min)
    delay = MAX_CHECK_MS - frac * (MAX_CHECK_MS - MIN_CHECK_MS)

    if mode == "PRESENT":
        # PRESENT mode: cap to keep Companion responsive.
        present_max = 3 * 60 * 1000 if follow_up_mode != "deepen" else 90 * 1000
        delay = min(delay, present_max)
    if mode == "PRESENT" and follow_up_mode == "deepen":
        delay *= 0.7

    return max(MIN_CHECK_MS, min(MAX_CHECK_MS, delay))


# ═══════════════════════════════════════════════════════════════
# PRESENT follow-up policy — light vs deepen (migrated from web-shell JS)
# ═══════════════════════════════════════════════════════════════

def resolve_present_follow_up_policy(user_msg_signal: Optional[dict], desire_level: float) -> dict:
    """Pick the PRESENT-mode follow-up posture from the last user message signal.

    deepen: 主动性更强 — 承接话题并往下推进半步（追问细节/接情绪）。
    light : 以承接话题为主 — 轻轻接一句，不深挖。
    """
    signal = user_msg_signal or {}
    need_care = float(signal.get("needCare", 0) or 0)
    intensity = float(signal.get("intensity", 0) or 0)
    has_question = bool(signal.get("hasQuestion", False))

    if need_care > 0.2:
        return {"mode": "deepen", "strategy": "follow_up_care", "threshold": 0.10}
    if has_question or intensity > 0.3 or desire_level >= 0.45:
        return {"mode": "deepen", "strategy": "follow_up_deepen", "threshold": 0.10}
    return {"mode": "light", "strategy": "follow_up_light", "threshold": 0.15}


def follow_up_mode_from_strategy(strategy: str) -> str:
    return "deepen" if strategy in ("follow_up_deepen", "follow_up_care") else "light"


def current_follow_up_mode(eng: "CompanionEngines") -> str:
    """Follow-up mode the scheduler should use right now."""
    if eng.life.interaction_mode != "PRESENT":
        return "light"
    return resolve_present_follow_up_policy(
        eng.life.last_user_msg_signal, eng.desire.desire_level
    )["mode"]


# ═══════════════════════════════════════════════════════════════
# Shared engine registry — state survives WebSocket disconnects
# and is driven by BOTH /chat/reply (normal mode) and LiveSession.
# ═══════════════════════════════════════════════════════════════

@dataclass
class CompanionEngines:
    """Bundle of all per-(user, contact) engine states."""
    life: LifeEngineState = field(default_factory=LifeEngineState)
    emotion: EmotionEngineState = field(default_factory=EmotionEngineState)
    desire: DesireState = field(default_factory=DesireState)
    persona: PersonaState = field(default_factory=PersonaState)
    last_decision: Optional[dict] = None   # last proactive decision snapshot
    last_tick_ts: float = 0.0              # for delta-based passive ticking


class StateRegistry:
    """Process-wide registry of CompanionEngines keyed by user::contact."""

    def __init__(self):
        self._by_key: dict[str, CompanionEngines] = {}

    @staticmethod
    def _key(user_id: str, contact_id: str) -> str:
        return f"{user_id}::{contact_id}"

    def get_or_create(self, user_id: str, contact_id: str) -> CompanionEngines:
        key = self._key(user_id, contact_id)
        eng = self._by_key.get(key)
        if eng is None:
            eng = CompanionEngines()
            self._by_key[key] = eng
        return eng

    def get(self, user_id: str, contact_id: str) -> Optional[CompanionEngines]:
        return self._by_key.get(self._key(user_id, contact_id))

    def items(self):
        """Iterate over (key, engines) for the background scheduler."""
        return list(self._by_key.items())


def emotion_urgency_peek(state: EmotionEngineState) -> float:
    """Non-mutating urgency read (emotion_check_for_signal decrements derailment)."""
    if state.state == "DISTRESSED":
        return min(1.0, 0.6 + state.derailment * 0.1)
    if state.state == "HEIGHTENED":
        return 0.4 + state.neg_weight * 0.3
    return 0.0


def engines_on_user_message(
    eng: CompanionEngines,
    now_ts: float,
    msg_text: str,
    recent_messages: list[dict],
) -> None:
    """Shared updates when a user message arrives (normal + live mode)."""
    life_on_user_message(eng.life, now_ts, msg_text)
    desire_nudge(eng.desire, eng.life.last_user_msg_signal)
    # Keyword-based VAD keeps the emotion engine alive without an extra LLM call.
    emotion_update(eng.emotion, emotion_keyword_fallback(recent_messages))


def engines_time_tick(eng: CompanionEngines, now_ts: float) -> None:
    """Delta-based passive time advance (normal mode; live mode has its scheduler)."""
    life_on_timer_tick(eng.life, now_ts)
    last = eng.last_tick_ts
    eng.last_tick_ts = now_ts
    if last <= 0:
        return
    delta_min = max(0.0, (now_ts - last) / 60.0)
    if delta_min < 0.05:  # ignore sub-3s polls
        return
    desire_accumulate(eng.desire, delta_min, emotion_urgency_peek(eng.emotion))


def engines_snapshot(eng: CompanionEngines) -> dict:
    """Full debug snapshot for the frontend panel."""
    now = time.time()
    idle_ms = (now - eng.life.last_interaction_ts) * 1000
    urgency = emotion_urgency_peek(eng.emotion)
    follow_up = current_follow_up_mode(eng)
    p = attention_probability(idle_ms, eng.life.interaction_mode, urgency, follow_up)
    threshold_policy = resolve_present_follow_up_policy(eng.life.last_user_msg_signal, eng.desire.desire_level)
    from app.engagement import engagement_snapshot
    return {
        "life": life_status(eng.life),
        "emotion": emotion_status(eng.emotion),
        "desire": desire_status(eng.desire),
        "engagement": engagement_snapshot(eng.desire),
        "threshold": f"{threshold_policy['threshold']:.2f}",
        "follow_up_mode": follow_up,
        "attention_p": f"{p:.3f}",
        "persona": {
            "energy": f"{eng.persona.energy:.2f}",
            "mood": f"{eng.persona.mood:.2f}",
            "motivation": eng.persona.motivation(),
            "receptive": eng.persona.is_receptive(),
        },
        "attention_p": f"{p:.3f}",
        "mode": eng.life.interaction_mode,
        "follow_up_mode": follow_up,
        "last_decision": eng.last_decision,
    }
