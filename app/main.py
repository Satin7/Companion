import os
import json
import asyncio
import time
import hashlib
import re
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from app.deepseek_client import DeepseekClient
from app.trigger_engine import TriggerEngine
from app.models import (
    StartSessionRequest,
    TriggerRequest,
    ProactiveDecisionRequest,
    ChatReplyRequest,
    ChatReplyResponse,
    ChatHistoryRequest,
    ChatHistoryResponse,
    ConversationMessage,
    MemoryProfile,
)
from app.sessions import SessionManager

app = FastAPI(title="Companion - Active AI Chat Framework")

deepseek = DeepseekClient(
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)


def _resolve_sqlite_path() -> str:
    configured = (os.getenv("SQLITE_DB_PATH", "") or "").strip()
    if configured:
        db_path = os.path.abspath(configured)
    else:
        # Default to workspace-local persistent storage.
        db_path = os.path.abspath(os.path.join(os.getcwd(), "data", "companion.db"))
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return db_path


sqlite_db = _resolve_sqlite_path()
session_manager = SessionManager(db_path=sqlite_db)
engine = TriggerEngine(deepseek_client=deepseek, session_manager=session_manager)


def _resolve_default_context_window() -> int:
    raw = (os.getenv("CHAT_CONTEXT_WINDOW", "40") or "40").strip()
    try:
        return max(1, int(raw))
    except Exception:
        return 40


DEFAULT_CHAT_CONTEXT_WINDOW = _resolve_default_context_window()
MEMORY_COOLDOWN_SEC = max(30, int((os.getenv("MEMORY_COOLDOWN_SEC", "600") or "600").strip()))
MEMORY_DEDUP_SEC = max(60, int((os.getenv("MEMORY_DEDUP_SEC", "21600") or "21600").strip()))
MEMORY_SCORE_THRESHOLD = int((os.getenv("MEMORY_SCORE_THRESHOLD", "3") or "3").strip())
MEMORY_BORDERLINE_LOW = int((os.getenv("MEMORY_BORDERLINE_LOW", "1") or "1").strip())
MEMORY_BORDERLINE_HIGH = int((os.getenv("MEMORY_BORDERLINE_HIGH", "2") or "2").strip())

_SMALL_TALK_WORDS = ["哈哈", "晚安", "早安", "在吗", "嗯", "哦", "好的", "好的呢"]
_FACT_WORDS = ["我喜欢", "我不喜欢", "我是", "我在", "我住", "我来自", "我习惯", "我平时"]
_PREFERENCE_CHANGE_WORDS = ["以后别", "不要再", "改成", "换成", "不想再", "希望你"]
_MAJOR_EVENT_WORDS = [
    "离职",
    "被裁",
    "裁员",
    "分手",
    "搬家",
    "生病",
    "住院",
    "手术",
    "确诊",
    "失业",
    "事故",
    "亲人",
    "考试",
]
_MAJOR_EVENT_NEGATIONS = ["不是", "没有", "并非", "没", "并没有"]
_MEMORY_PIPELINE_LOCKS: dict[str, asyncio.Lock] = {}


def _log_memory(event: str, **kwargs) -> None:
    data = {"tag": "memory", "event": event, **kwargs}
    print(json.dumps(data, ensure_ascii=False))


def _normalize_text(text: str) -> str:
    s = (text or "").strip().lower()
    return re.sub(r"\s+", " ", s)


def _hash_text(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def _contains_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def _major_event_signal(text: str) -> dict:
    normalized = _normalize_text(text)
    hit_words = [w for w in _MAJOR_EVENT_WORDS if w in normalized]
    if not hit_words:
        return {"is_major": False, "event_type": "", "confidence": 0.0, "reason": ""}
    negated = any(n in normalized for n in _MAJOR_EVENT_NEGATIONS)
    if negated:
        return {"is_major": False, "event_type": "", "confidence": 0.0, "reason": "negated_major_event"}

    event_type = "life_change"
    if any(w in normalized for w in ["生病", "住院", "手术", "确诊"]):
        event_type = "health"
    elif any(w in normalized for w in ["离职", "被裁", "裁员", "失业"]):
        event_type = "career"
    elif any(w in normalized for w in ["分手"]):
        event_type = "relationship"
    elif any(w in normalized for w in ["搬家"]):
        event_type = "relocation"
    elif any(w in normalized for w in ["考试"]):
        event_type = "exam"

    confidence = min(0.99, 0.7 + 0.08 * len(hit_words))
    return {
        "is_major": True,
        "event_type": event_type,
        "confidence": confidence,
        "reason": "major_event_keyword",
        "hits": hit_words,
    }


def _rule_memory_decision(message: str) -> dict:
    text = (message or "").strip()
    normalized = _normalize_text(text)
    score = 0
    reasons = []

    if len(text) < 8:
        score -= 1
        reasons.append("short_text")

    if _contains_any(normalized, _SMALL_TALK_WORDS):
        score -= 2
        reasons.append("small_talk")

    if _contains_any(normalized, _FACT_WORDS):
        score += 2
        reasons.append("fact_signal")

    if _contains_any(normalized, _PREFERENCE_CHANGE_WORDS):
        score += 3
        reasons.append("preference_change")

    major = _major_event_signal(text)
    if major.get("is_major"):
        score += 4
        reasons.append("major_event")

    should_write = score >= MEMORY_SCORE_THRESHOLD or bool(major.get("is_major"))
    borderline_high = min(MEMORY_BORDERLINE_HIGH, MEMORY_SCORE_THRESHOLD - 1)
    borderline = MEMORY_BORDERLINE_LOW <= score <= borderline_high and not should_write
    return {
        "should_write": should_write,
        "score": score,
        "reasons": reasons,
        "major": major,
        "borderline": borderline,
    }


async def _ds_borderline_memory_judge(message: str, recent_history: list[dict], api_key: str | None) -> dict:
    history_lines = []
    for item in recent_history[-6:]:
        role = "用户" if item.get("role") == "user" else "AI"
        content = str(item.get("content", "")).strip()
        if content:
            history_lines.append(f"{role}: {content[:120]}")
    convo = "\n".join(history_lines)
    prompt = f"""你是记忆写入判定器。请判断最后一条用户消息是否值得写入长期记忆。

最近对话:
{convo}

最后一条用户消息:
{message}

仅输出 JSON:
{{
  "should_store": true,
  "memory_level": "working|episodic|semantic",
  "confidence": 0.0,
  "reason": "简短原因"
}}
"""
    try:
        result = await deepseek.chat_complete(
            messages=[{"role": "system", "content": prompt}],
            max_tokens=180,
            api_key=api_key,
        )
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _extract_json(content)
        if not parsed:
            return {"used": True, "should_store": False, "memory_level": "semantic", "confidence": 0.0, "reason": "ds_parse_failed"}
        should_store = bool(parsed.get("should_store", False))
        memory_level = str(parsed.get("memory_level", "semantic") or "semantic").strip()
        if memory_level not in ["working", "episodic", "semantic"]:
            memory_level = "semantic"
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        return {
            "used": True,
            "should_store": should_store,
            "memory_level": memory_level,
            "confidence": max(0.0, min(1.0, confidence)),
            "reason": str(parsed.get("reason", "") or "").strip()[:120],
        }
    except Exception:
        return {"used": True, "should_store": False, "memory_level": "semantic", "confidence": 0.0, "reason": "ds_judge_error"}


def _make_memory_dedup_key(user_message: str, major: dict) -> str:
    normalized = _normalize_text(user_message)
    major_type = str(major.get("event_type", "") or "none")
    return f"{major_type}:{_hash_text(normalized)}"


def _build_working_memory(history: list[dict]) -> list[dict]:
    items = []
    for msg in history[-6:]:
        role = str(msg.get("role", "")).strip()
        content = str(msg.get("content", "")).strip()
        if role and content:
            items.append({"role": role, "content": content[:180]})
    return items


def _build_episodic_memory(existing_timeline: list[dict], major: dict, user_message: str) -> list[dict]:
    timeline = [item for item in existing_timeline if isinstance(item, dict)]
    if major.get("is_major"):
        now = time.strftime("%m-%d", time.localtime())
        timeline.append(
            {
                "date": now,
                "topic": f"major:{major.get('event_type', 'life_change')}",
                "notes": str(user_message or "").strip()[:180],
                "confidence": float(major.get("confidence", 0.0) or 0.0),
            }
        )
    return timeline[-20:]


def _build_semantic_memory(summary: str, facts: list[str], patterns: str) -> dict:
    clean_facts = [str(x).strip() for x in facts if str(x).strip()]
    dedup = []
    seen = set()
    for item in clean_facts:
        if item in seen:
            continue
        seen.add(item)
        dedup.append(item)
    return {
        "summary": str(summary or "").strip(),
        "facts": dedup[:80],
        "patterns": str(patterns or "").strip(),
    }


def _meta_float(meta: dict, key: str) -> float:
    try:
        return float(meta.get(key, 0.0) or 0.0)
    except Exception:
        return 0.0


def _memory_lock_key(user_id: str, contact_id: str) -> str:
    return f"{user_id}::{contact_id}"


def _get_memory_lock(user_id: str, contact_id: str) -> asyncio.Lock:
    key = _memory_lock_key(user_id, contact_id)
    lock = _MEMORY_PIPELINE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _MEMORY_PIPELINE_LOCKS[key] = lock
    return lock


def _memory_context(memory: dict) -> str:
    parts = []
    summary = (memory.get("summary") or "").strip()
    facts = memory.get("facts") or []
    patterns = (memory.get("patterns") or "").strip()
    timeline = memory.get("timeline") or []

    if summary:
        parts.append(summary)
    if facts:
        parts.append("已知信息: " + "；".join([str(f).strip() for f in facts if str(f).strip()]))
    if patterns:
        parts.append(patterns)
    if timeline:
        recents = []
        for item in timeline[-5:]:
            date = str(item.get("date", "")).strip()
            topic = str(item.get("topic", "")).strip()
            if date or topic:
                recents.append(f"{date}: {topic}".strip(": "))
        if recents:
            parts.append("近期时间线: " + "；".join(recents))

    if not parts:
        return ""
    return "\n关于用户（融入回复，不要机械复述）：\n" + "\n".join(parts)


def _extract_json(text: str) -> dict | None:
    content = (text or "").replace("```json", "").replace("```", "").strip()
    if not content:
        return None
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    s = content.find("{")
    e = content.rfind("}")
    if s >= 0 and e > s:
        try:
            parsed = json.loads(content[s : e + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


async def _update_memory_from_history(
    user_id: str,
    contact_id: str,
    history: list[dict],
    existing_memory: dict,
    api_key: str | None,
) -> dict:
    if len(history) < 2:
        return existing_memory

    window = history[-300:]
    history_text = "\n".join(
        [f"{'用户' if m.get('role') == 'user' else 'AI'}: {str(m.get('content', ''))}" for m in window]
    )
    existing_json = json.dumps(
        {
            "summary": existing_memory.get("summary", ""),
            "timeline": existing_memory.get("timeline", []),
            "facts": existing_memory.get("facts", []),
            "patterns": existing_memory.get("patterns", ""),
        },
        ensure_ascii=False,
    )
    prompt = f"""你是长期记忆助手。请根据对话历史，更新用户记忆。

现有记忆:
{existing_json}

对话历史:
{history_text}

输出纯 JSON（不要 markdown）：
{{
  "summary": "200-400字整体画像",
  "timeline": [{{"date":"MM-DD","topic":"简短标题","notes":"关键内容"}}],
  "facts": ["长期有用的事实"],
  "patterns": "100-200字行为/情绪规律"
}}

要求：
- 允许保留并改写旧记忆，避免丢失有价值信息
- facts 去重，timeline 保留最近 20 条
- 仅输出 JSON
"""
    try:
        result = await deepseek.chat_complete(
            messages=[{"role": "system", "content": prompt}],
            max_tokens=1500,
            api_key=api_key,
        )
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _extract_json(content)
        if not parsed:
            return existing_memory
        updated = {
            "summary": str(parsed.get("summary", "") or "").strip(),
            "timeline": parsed.get("timeline", []) if isinstance(parsed.get("timeline", []), list) else [],
            "facts": parsed.get("facts", []) if isinstance(parsed.get("facts", []), list) else [],
            "patterns": str(parsed.get("patterns", "") or "").strip(),
        }
        # timeline trim + facts dedup
        updated["timeline"] = updated["timeline"][-20:]
        seen = set()
        dedup_facts = []
        for fact in updated["facts"]:
            text = str(fact).strip()
            if not text:
                continue
            if text in seen:
                continue
            seen.add(text)
            dedup_facts.append(text)
        updated["facts"] = dedup_facts
        return updated
    except Exception:
        return existing_memory


async def _run_memory_pipeline(
    session_id: str,
    user_id: str,
    contact_id: str,
    user_message: str,
    api_key: str | None,
) -> tuple[dict, str]:
    async with _get_memory_lock(user_id, contact_id):
        existing_memory = session_manager.get_memory(user_id=user_id, contact_id=contact_id)
        meta = existing_memory.get("meta", {}) if isinstance(existing_memory.get("meta", {}), dict) else {}
        rule = _rule_memory_decision(user_message)
        dedup_key = _make_memory_dedup_key(user_message, rule.get("major", {}))

        should_write = bool(rule.get("should_write", False))
        memory_level = "semantic"
        reason_code = "rule_skip"
        ds_used = False

        if should_write:
            reason_code = "rule_pass"
            if rule.get("major", {}).get("is_major"):
                reason_code = "major_event"
                memory_level = "episodic"
        elif rule.get("borderline"):
            recent = session_manager.get_context(session_id, limit=12)
            ds = await _ds_borderline_memory_judge(user_message, recent_history=recent, api_key=api_key)
            ds_used = bool(ds.get("used"))
            if ds.get("should_store"):
                should_write = True
                memory_level = str(ds.get("memory_level", "semantic") or "semantic")
                reason_code = "ds_borderline_pass"
            else:
                reason_code = str(ds.get("reason", "ds_borderline_skip") or "ds_borderline_skip")

        if not should_write:
            _log_memory("decision_skip", user_id=user_id, contact_id=contact_id, reason=reason_code, score=rule.get("score", 0), ds_used=ds_used)
            return existing_memory, reason_code

        now_ts = time.time()
        major = bool(rule.get("major", {}).get("is_major"))
        last_write_ts = _meta_float(meta, "last_write_ts")
        if (not major) and last_write_ts > 0 and now_ts - last_write_ts < MEMORY_COOLDOWN_SEC:
            _log_memory("cooldown_skip", user_id=user_id, contact_id=contact_id, seconds_left=int(MEMORY_COOLDOWN_SEC - (now_ts - last_write_ts)), reason=reason_code)
            return existing_memory, "cooldown_skip"

        last_dedup_key = str(meta.get("last_dedup_key", "") or "")
        last_dedup_ts = _meta_float(meta, "last_dedup_ts")
        if dedup_key == last_dedup_key and (now_ts - last_dedup_ts) < MEMORY_DEDUP_SEC:
            _log_memory("dedup_skip", user_id=user_id, contact_id=contact_id, reason=reason_code)
            return existing_memory, "dedup_skip"

        full_history = session_manager.get_context(session_id, limit=0)
        updated = await _update_memory_from_history(
            user_id=user_id,
            contact_id=contact_id,
            history=full_history,
            existing_memory=existing_memory,
            api_key=api_key,
        )

        if not isinstance(updated, dict) or updated == existing_memory:
            _log_memory("update_no_change", user_id=user_id, contact_id=contact_id, reason=reason_code)
            return existing_memory, "update_no_change"

        semantic_memory = _build_semantic_memory(
            summary=updated.get("summary", ""),
            facts=updated.get("facts", []),
            patterns=updated.get("patterns", ""),
        )
        episodic_memory = _build_episodic_memory(
            existing_timeline=updated.get("timeline", []),
            major=rule.get("major", {}),
            user_message=user_message,
        )
        working_memory = _build_working_memory(full_history)

        new_meta = dict(meta)
        new_meta.update(
            {
                "last_write_ts": now_ts,
                "last_reason_code": reason_code,
                "last_dedup_key": dedup_key,
                "last_dedup_ts": now_ts,
                "last_score": int(rule.get("score", 0) or 0),
                "last_memory_level": memory_level,
                "ds_borderline_used": ds_used,
            }
        )
        if major:
            new_meta["last_major_event"] = {
                "event_type": rule.get("major", {}).get("event_type", ""),
                "confidence": float(rule.get("major", {}).get("confidence", 0.0) or 0.0),
                "at": now_ts,
            }

        persisted = {
            "summary": updated.get("summary", ""),
            "timeline": episodic_memory,
            "facts": semantic_memory.get("facts", []),
            "patterns": semantic_memory.get("patterns", ""),
            "schema_version": "1.0",
            "working_memory": working_memory,
            "episodic_memory": episodic_memory,
            "semantic_memory": semantic_memory,
            "meta": new_meta,
        }
        session_manager.upsert_memory(user_id=user_id, contact_id=contact_id, memory=persisted)
        final_memory = session_manager.get_memory(user_id=user_id, contact_id=contact_id)
        _log_memory(
            "updated",
            user_id=user_id,
            contact_id=contact_id,
            reason=reason_code,
            score=rule.get("score", 0),
            memory_level=memory_level,
            major_event=major,
            ds_used=ds_used,
        )
        return final_memory, reason_code


async def _update_memory_background(
    session_id: str,
    user_id: str,
    contact_id: str,
    user_message: str,
    api_key: str | None,
) -> None:
    try:
        await _run_memory_pipeline(
            session_id=session_id,
            user_id=user_id,
            contact_id=contact_id,
            user_message=user_message,
            api_key=api_key,
        )
    except Exception:
        # Memory update failures should never impact main reply flow.
        _log_memory("update_error", user_id=user_id, contact_id=contact_id)
        return


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/sessions/start")
async def start_session(req: StartSessionRequest):
    contact_id = "default"
    if req.metadata and isinstance(req.metadata, dict):
        contact_id = str(req.metadata.get("contact_id", "default") or "default")
    session_id = session_manager.create_session(req.user_id, contact_id=contact_id, metadata=req.metadata)
    return {"session_id": session_id}


@app.post("/chat/history", response_model=ChatHistoryResponse)
async def chat_history(req: ChatHistoryRequest):
    session_id = session_manager.get_or_create_session(req.user_id, contact_id=req.contact_id)
    limit = max(0, int(req.limit))
    history = session_manager.get_context(session_id, limit=limit)
    memory = session_manager.get_memory(req.user_id, contact_id=req.contact_id)
    return ChatHistoryResponse(
        session_id=session_id,
        messages=[ConversationMessage(role=m.get("role", "assistant"), content=m.get("content", "")) for m in history],
        memory=MemoryProfile(**memory),
    )


@app.post("/chat/reply", response_model=ChatReplyResponse)
async def chat_reply(
    req: ChatReplyRequest,
    authorization: str | None = Header(default=None),
    x_deepseek_api_key: str | None = Header(default=None),
):
    key = x_deepseek_api_key
    if not key and authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()

    session_id = session_manager.get_or_create_session(req.user_id, contact_id=req.contact_id)
    session_manager.append_message(session_id=session_id, role="user", text=req.message)

    memory = session_manager.get_memory(req.user_id, contact_id=req.contact_id)
    default_prompt = "你是一个温暖、理性、能干的AI伴侣。请用中文简短回复用户（2-4句话）。"
    prompt = (req.system_prompt or default_prompt).strip() + _memory_context(memory)

    if req.context_window is None:
        context_limit = DEFAULT_CHAT_CONTEXT_WINDOW
    else:
        context_limit = max(0, int(req.context_window))

    history = session_manager.get_context(session_id, limit=context_limit)
    llm_messages = [{"role": "system", "content": prompt}] + [
        {"role": m.get("role", "user"), "content": m.get("content", "")} for m in history
    ]

    try:
        result = await deepseek.chat_complete(
            messages=llm_messages,
            max_tokens=max(64, int(req.max_tokens or 1024)),
            api_key=key,
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream model timeout. Please retry.")
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else 502
        raise HTTPException(status_code=status, detail=f"Upstream model HTTP error: {status}")
    except Exception:
        raise HTTPException(status_code=502, detail="Upstream model request failed.")
    reply = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    session_manager.append_message(session_id=session_id, role="assistant", text=reply)

    history_count = session_manager.count_messages(session_id)
    if req.update_memory:
        if req.memory_update_async:
            asyncio.create_task(
                _update_memory_background(
                    session_id=session_id,
                    user_id=req.user_id,
                    contact_id=req.contact_id,
                    user_message=req.message,
                    api_key=key,
                )
            )
        else:
            memory, _ = await _run_memory_pipeline(
                session_id=session_id,
                user_id=req.user_id,
                contact_id=req.contact_id,
                user_message=req.message,
                api_key=key,
            )

    return ChatReplyResponse(
        session_id=session_id,
        reply=reply,
        history_count=history_count,
        memory=MemoryProfile(**memory),
    )


@app.post("/triggers/evaluate")
async def evaluate_trigger(req: TriggerRequest):
    ok = await engine.evaluate_trigger(req)
    return {"triggered": ok}


@app.post("/proactive/decision")
async def proactive_decision(
    req: ProactiveDecisionRequest,
    authorization: str | None = Header(default=None),
    x_deepseek_api_key: str | None = Header(default=None),
):
    key = x_deepseek_api_key
    if not key and authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
    try:
        return await engine.decide_proactive(req, api_key_override=key)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream decision timeout. Please retry.")
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else 502
        raise HTTPException(status_code=status, detail=f"Upstream decision HTTP error: {status}")
    except Exception:
        raise HTTPException(status_code=502, detail="Upstream decision request failed.")


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    engine.register_connection(user_id, websocket)
    try:
        while True:
            # simple echo/keepalive receiver
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        engine.unregister_connection(user_id, websocket)
