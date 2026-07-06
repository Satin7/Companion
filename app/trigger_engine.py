from typing import Any, Dict, List, Optional
from fastapi import WebSocket
import asyncio
import json
from app.deepseek_client import DeepseekClient
from app.models import TriggerRequest, TriggerAction, TriggerCondition
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
