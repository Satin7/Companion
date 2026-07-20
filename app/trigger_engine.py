from typing import Any, Dict, List, Optional
from fastapi import WebSocket
import asyncio
import json
import logging
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
from app.state_engine import (
    resolve_present_follow_up_policy,
    follow_up_mode_from_strategy,
)

logger = logging.getLogger("companion.trigger")


class TriggerEngine:
    def __init__(self, deepseek_client: DeepseekClient, session_manager: Optional[SessionManager] = None):
        self.deepseek = deepseek_client
        self.triggers: List[Dict[str, Any]] = []
        self.connections: Dict[str, List[WebSocket]] = {}
        self.session_manager = session_manager
        self._lock = asyncio.Lock()
        self.last_proactive_debug: Dict[str, Any] = {}

    def get_last_proactive_debug(self) -> Dict[str, Any]:
        return dict(self.last_proactive_debug)

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
            signal = life.user_msg_signal if life and life.user_msg_signal else None
            return resolve_present_follow_up_policy(signal, req.desire_level)["strategy"]

        if emotion and emotion.urgency > 0.5:
            return "check_in"
        if req.consecutive_no_reply > 3 and req.desire_level > 0.7:
            return "keep_company"
        return "reduce_frequency"

    def _min_desire_for(self, req: ProactiveDecisionRequest) -> float:
        """Desire threshold below which Companion stays silent."""
        mode = (req.interaction_mode or "ABSENT").upper()
        if mode == "PRESENT":
            signal = req.life_event.user_msg_signal if req.life_event and req.life_event.user_msg_signal else None
            return resolve_present_follow_up_policy(signal, req.desire_level)["threshold"]
        return 0.5

    async def decide_proactive(
        self,
        req: ProactiveDecisionRequest,
        api_key_override: Optional[str] = None,
    ) -> ProactiveDecisionResponse:
        if req.test_mode:
            now_ms = int(req.now_ts_ms or (time.time() * 1000))
            last_ms = int(req.last_proactive_sent_ms or 0)
            # No anchor yet (direct API caller) → first message is due immediately
            due = last_ms <= 0 or (now_ms - last_ms) >= 60_000
            return ProactiveDecisionResponse(
                should_speak=due,
                topic_hint="测试模式问候" if due else None,
                confidence=1.0,
                strategy="test_interval_1m",
                follow_up_mode="light",
            )

        mode = (req.interaction_mode or "ABSENT").upper()
        has_signal = bool(req.life_event or req.emotion_event)
        strategy = self._strategy_for(req)
        follow_up_mode = follow_up_mode_from_strategy(strategy)
        min_desire = self._min_desire_for(req)
        if not has_signal and req.desire_level < min_desire:
            return ProactiveDecisionResponse(
                should_speak=False,
                topic_hint=None,
                confidence=0.0,
                strategy=strategy,
                follow_up_mode=follow_up_mode,
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
        if mode == "PRESENT":
            sys_prompt = (
                "你是主动陪伴决策引擎。当前处于 PRESENT 模式：用户正在和 Companion 实时聊天。"
                "根据上下文，判断现在是否应该主动承接一句、追问一小步，或自然延续话题。\n"
                "只输出严格 JSON：{\"shouldSpeak\":bool,\"topicHint\":\"简短中文话题提示或null\",\"confidence\":0.0-1.0}\n"
                "判断原则：\n"
                "- PRESENT 不是留言打扰场景，而是实时对话承接场景\n"
                "- 只要存在轻度连接欲望，或刚出现适合追问/接话的点，就可以主动\n"
                "- 用户情绪低落、刚提出问题、话题有展开空间时，更应该主动\n"
                "- 如果上一轮已经完整收束、继续接话会显得突兀，再选择不发\n"
                "- topicHint 用简短中文描述，例如「顺着他刚才的问题追问一句」，不要长篇大论"
            )
        else:
            sys_prompt = (
                "你是主动陪伴决策引擎。根据当前上下文，判断现在是否应该主动发起一条消息。\n"
                "只输出严格 JSON：{\"shouldSpeak\":bool,\"topicHint\":\"简短中文话题提示或null\",\"confidence\":0.0-1.0}\n"
                "判断原则：\n"
                "- 无强信号时保守，默认不发\n"
                "- 用户情绪低落或明显需要关心时，适当主动\n"
                "- 连续未回复超过 2 次，减少频率，避免骚扰\n"
                "- topicHint 用简短中文描述，例如「关心一下睡眠情况」，不要长篇大论"
            )

        try:
            ds_messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)},
            ]
            self.last_proactive_debug = {
                "at": time.time(),
                "request": {
                    "model": "deepseek-v4-pro",
                    "max_tokens": 180,
                    "temperature": 0.9,
                    "messages": ds_messages,
                },
                "context": ctx,
                "strategy": strategy,
                "test_mode": False,
            }
            response = await self.deepseek.chat_complete(
                messages=ds_messages,
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
            s = content.find("{")
            e = content.rfind("}")
            if s == -1 or e == -1:
                raise ValueError(f"No JSON found in LLM response: {content[:100]}")
            payload = json.loads(content[s : e + 1])
            self.last_proactive_debug["response"] = {
                "raw": content,
                "parsed": payload,
            }
            return ProactiveDecisionResponse(
                should_speak=bool(payload.get("shouldSpeak", False)),
                topic_hint=payload.get("topicHint") or None,
                confidence=float(payload.get("confidence", 0.0) or 0.0),
                strategy=strategy,
                follow_up_mode=follow_up_mode,
            )
        except Exception:
            logger.warning("decide_proactive LLM call failed — falling back to should_speak=False")
            self.last_proactive_debug = {
                "at": time.time(),
                "request": {
                    "model": "deepseek-v4-pro",
                    "max_tokens": 180,
                    "temperature": 0.9,
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)},
                    ],
                },
                "context": ctx,
                "strategy": strategy,
                "test_mode": False,
                "fallback": True,
            }
            return ProactiveDecisionResponse(
                should_speak=False,
                topic_hint=None,
                confidence=0.0,
                strategy=strategy,
                follow_up_mode=follow_up_mode,
            )
