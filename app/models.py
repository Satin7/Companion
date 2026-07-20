from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List


class StartSessionRequest(BaseModel):
    user_id: str
    metadata: Optional[Dict[str, Any]] = None


class TriggerCondition(BaseModel):
    type: str
    params: Dict[str, Any] = {}


class TriggerAction(BaseModel):
    type: str
    params: Dict[str, Any] = {}


class TriggerRequest(BaseModel):
    user_id: str
    condition: TriggerCondition
    action: TriggerAction


class ConversationMessage(BaseModel):
    role: str
    content: str


class HistoryMessage(BaseModel):
    role: str
    content: str
    segments: Optional[List[str]] = None
    is_proactive: bool = False
    audio_url: Optional[str] = None
    audio_urls: Optional[List[str]] = None


class LifeEvent(BaseModel):
    reason: str
    idle_minutes: Optional[int] = None
    context_hint: Optional[str] = None
    user_msg_signal: Optional[Dict[str, Any]] = None


class EmotionEvent(BaseModel):
    reason: str
    urgency: float = 0.0
    valence: Optional[float] = None
    arousal: Optional[float] = None


class ProactiveDecisionRequest(BaseModel):
    user_id: str = "default"
    interaction_mode: str = "ABSENT"
    desire_level: float = 0.0
    consecutive_no_reply: int = 0
    test_mode: bool = False
    now_ts_ms: Optional[int] = None
    last_proactive_sent_ms: Optional[int] = None
    messages: List[ConversationMessage] = []
    life_event: Optional[LifeEvent] = None
    emotion_event: Optional[EmotionEvent] = None


class ProactiveDecisionResponse(BaseModel):
    should_speak: bool
    topic_hint: Optional[str] = None
    confidence: float = 0.0
    strategy: str = "reduce_frequency"
    follow_up_mode: str = "light"


class ProactiveGenerateRequest(BaseModel):
    user_id: str = "default"
    contact_id: str = "default"
    interaction_mode: str = "ABSENT"
    follow_up_mode: str = "light"
    topic_hint: Optional[str] = None
    messages: List[ConversationMessage] = []
    voice_mode: bool = False
    voice: Optional[str] = None


class ProactiveGenerateResponse(BaseModel):
    message: str
    message_segments: List[str] = Field(default_factory=list)
    audio_url: Optional[str] = None


class ChatReplyRequest(BaseModel):
    user_id: str = "default"
    contact_id: str = "default"
    message: str
    system_prompt: Optional[str] = None
    max_tokens: int = 1024
    context_window: Optional[int] = None
    update_memory: bool = True
    memory_update_async: bool = True
    voice_mode: bool = False
    voice: Optional[str] = None


class ChatHistoryRequest(BaseModel):
    user_id: str = "default"
    contact_id: str = "default"
    limit: int = 500


class MemoryProfile(BaseModel):
    summary: str = ""
    timeline: List[Dict[str, Any]] = []
    facts: List[str] = []
    patterns: str = ""
    schema_version: str = "1.0"
    working_memory: List[Dict[str, Any]] = []
    episodic_memory: List[Dict[str, Any]] = []
    semantic_memory: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}
    updated_at: Optional[str] = None


class ChatReplyResponse(BaseModel):
    session_id: str
    reply: str
    reply_segments: List[str] = Field(default_factory=list)
    history_count: int
    memory: MemoryProfile
    audio_url: Optional[str] = None
    audio_urls: Optional[List[str]] = None
    engagement: Optional[Dict[str, Any]] = None


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: List[HistoryMessage]
    memory: MemoryProfile


# ═══════════════════════════════════════════════════════════════
# Live Mode — WebSocket protocol messages
# ═══════════════════════════════════════════════════════════════

class LiveEvent(BaseModel):
    """Incoming event from client via WebSocket."""
    type: str
    text: Optional[str] = None
    mode: Optional[str] = None
    active: Optional[bool] = None
    idle_ms: Optional[int] = None


class LiveReplyStart(BaseModel):
    type: str = "reply.start"
    reply_id: str
    mode: str  # "chat" | "proactive"


class LiveToken(BaseModel):
    type: str = "reply.token"
    reply_id: str
    token: str


class LiveReplyEnd(BaseModel):
    type: str = "reply.end"
    reply_id: str
    full_text: str
    segments: List[str] = Field(default_factory=list)
    memory: Optional[MemoryProfile] = None


class LiveProactiveStart(BaseModel):
    type: str = "proactive.start"
    reply_id: str
    strategy: str
    topic_hint: Optional[str] = None


class LiveThinkingState(BaseModel):
    type: str = "thinking.state"
    desire: str
    attention_p: str
    emotion_state: str
    life_state: str
    mode: str
    idle_min: str
    persona_mood: str


class LiveThinkingDecision(BaseModel):
    type: str = "thinking.decision"
    strategy: str
    should_speak: bool
    confidence: float
    topic_hint: Optional[str] = None
    factors: dict = Field(default_factory=dict)


class LiveCompanionTyping(BaseModel):
    type: str = "companion.typing"
    active: bool


class LiveError(BaseModel):
    type: str = "error"
    code: str
    detail: str = ""
