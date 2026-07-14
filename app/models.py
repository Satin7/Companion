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


class ProactiveGenerateRequest(BaseModel):
    user_id: str = "default"
    contact_id: str = "default"
    interaction_mode: str = "ABSENT"
    topic_hint: Optional[str] = None
    messages: List[ConversationMessage] = []


class ProactiveGenerateResponse(BaseModel):
    message: str
    message_segments: List[str] = Field(default_factory=list)


class ChatReplyRequest(BaseModel):
    user_id: str = "default"
    contact_id: str = "default"
    message: str
    system_prompt: Optional[str] = None
    max_tokens: int = 1024
    context_window: Optional[int] = None
    update_memory: bool = True
    memory_update_async: bool = True


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


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: List[ConversationMessage]
    memory: MemoryProfile
