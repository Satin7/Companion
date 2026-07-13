from typing import Any, Dict, List, Optional
from fastapi import WebSocket
import asyncio
import json
import time
from app.deepseek_client import DeepseekClient
from app.models import (
    TriggerRequest,
    TriggerAction,
    TriggerCondition,
    ProactiveDecisionRequest,
    ProactiveDecisionResponse,
)
from app.sessions import SessionManager


class TriggerEngine:
    def __init__(self, deepseek_client: DeepseekClient, session_manager: Optional[SessionManager] = None):
        self.deepseek = deepseek_client
        self.triggers: List[Dict[str, Any]] = []
        self.connections: Dict[str, List[WebSocket]] = {}
        self.session_manager = session_manager
        self._lock = asyncio.Lock()

    def register_trigger(self, trigger_def: Dict[str, Any]) -> str:
        tid = trigger_def.get("id") or f"trig_{len(self.triggers)+1}"
        trigger_def["id"] = tid
        self.triggers.append(trigger_def)
        return tid

    def unregister_trigger(self, trigger_id: str) -> bool:
        before = len(self.triggers)
        self.triggers = [t for t in self.triggers if t.get("id") != trigger_id]
        return len(self.triggers) < before

    def register_connection(self, user_id: str, websocket: WebSocket):
        conns = self.connections.setdefault(user_id, [])
        conns.append(websocket)

    def unregister_connection(self, user_id: str, websocket: WebSocket):
        conns = self.connections.get(user_id)
        if not conns:
            return
        try:
            conns.remove(websocket)
        except ValueError:
            pass

    async def _send_to_user(self, user_id: str, payload: Dict[str, Any]):
        conns = self.connections.get(user_id, [])
        if not conns:
            return
        for ws in list(conns):
            try:
                await ws.send_json(payload)
            except Exception:
                # Best-effort; remove bad connection
                try:
                    conns.remove(ws)
                except ValueError:
                    pass

    async def evaluate_condition(self, condition: TriggerCondition, context: Dict[str, Any]) -> bool:
        if condition.type == "deepseek_search":
            query = condition.params.get("query", "")
            if not query:
                return False
            res = await self.deepseek.search(query)
            # heuristic: check for results list or items
            if isinstance(res, dict):
                return bool(res.get("results") or res.get("items") or res)
            return bool(res)
        # placeholder for other condition types
        return False

    async def execute_action(self, action: TriggerAction, user_id: str, session_id: Optional[str] = None):
        if action.type == "message":
            text = action.params.get("text", "")
            payload = {"type": "message", "text": text}
            # append to session if we have a session manager
            if self.session_manager and session_id:
                self.session_manager.append_message(session_id, role="assistant", text=text)
            await self._send_to_user(user_id, payload)
        # other actions (push, webhook) can be added later

    async def evaluate_trigger(self, req: TriggerRequest) -> bool:
        cond = req.condition
        action = req.action
        context = {"user_id": req.user_id}
        ok = await self.evaluate_condition(cond, context)
        if ok:
            # create or reuse session
            session_id = None
            if self.session_manager:
                session_id = self.session_manager.create_session(req.user_id)
                # record trigger reason
                self.session_manager.append_message(session_id, role="system", text=json.dumps({"trigger": cond.dict(), "action": action.dict()}))
            await self.execute_action(action, req.user_id, session_id=session_id)
        return ok

    def _strategy_for(self, req: ProactiveDecisionRequest) -> str:
        mode = (req.interaction_mode or "ABSENT").upper()
        life = req.life_event
        emotion = req.emotion_event

        if mode == "PRESENT":
            need_care = 0.0
            has_question = False
            if life and life.user_msg_signal:
                need_care = float(life.user_msg_signal.get("needCare", 0.0) or 0.0)
                has_question = bool(life.user_msg_signal.get("hasQuestion", False))
            if need_care > 0.2:
                return "follow_up_care"
            if has_question:
                return "follow_up_deepen"
            return "follow_up_light"

        if emotion and emotion.urgency > 0.5:
            return "check_in"
        if req.consecutive_no_reply > 3 and req.desire_level > 0.7:
            return "keep_company"
        return "reduce_frequency"

    async def decide_proactive(
        self,
        req: ProactiveDecisionRequest,
        api_key_override: Optional[str] = None,
    ) -> ProactiveDecisionResponse:
        if req.test_mode:
            now_ms = int(req.now_ts_ms or (time.time() * 1000))
            last_ms = int(req.last_proactive_sent_ms or now_ms)
            due = (now_ms - last_ms) >= 60_000
            return ProactiveDecisionResponse(
                should_speak=due,
                topic_hint="测试模式问候" if due else None,
                confidence=1.0,
                strategy="test_interval_1m",
            )

        has_signal = bool(req.life_event or req.emotion_event)
        strategy = self._strategy_for(req)
        if not has_signal and req.desire_level < 0.5:
            return ProactiveDecisionResponse(
                should_speak=False,
                topic_hint=None,
                confidence=0.0,
                strategy=strategy,
            )

        ctx = {
            "interactionMode": req.interaction_mode,
            "strategy": strategy,
            "desireLevel": round(req.desire_level, 3),
            "consecutiveNoReply": req.consecutive_no_reply,
            "recentConversation": [
                {"role": m.role, "content": (m.content or "")[:200]} for m in req.messages[-8:]
            ],
            "lifeEvent": req.life_event.dict() if req.life_event else None,
            "emotionEvent": req.emotion_event.dict() if req.emotion_event else None,
        }
        sys_prompt = (
            "You are a proactive companion decision engine. "
            "Decide whether the assistant should proactively speak now. "
            "Return strict JSON only: "
            '{"shouldSpeak":bool,"topicHint":"short Chinese hint or null","confidence":0.0-1.0}. '
            "Be conservative when no strong signal exists."
        )

        try:
            response = await self.deepseek.chat_complete(
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)},
                ],
                max_tokens=180,
                api_key=api_key_override,
            )
            content = (
                response.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )
            payload = json.loads(content[content.find("{") : content.rfind("}") + 1])
            return ProactiveDecisionResponse(
                should_speak=bool(payload.get("shouldSpeak", False)),
                topic_hint=payload.get("topicHint") or None,
                confidence=float(payload.get("confidence", 0.0) or 0.0),
                strategy=strategy,
            )
        except Exception:
            fallback_should_speak = has_signal and req.desire_level >= 0.2
            return ProactiveDecisionResponse(
                should_speak=fallback_should_speak,
                topic_hint=None,
                confidence=0.3 if fallback_should_speak else 0.0,
                strategy=strategy,
            )
