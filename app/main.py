import os
import json
import asyncio
import logging
import time
import hashlib
import re
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from app.deepseek_client import DeepseekClient
from app.trigger_engine import TriggerEngine

# Make companion.* loggers (live/proactive scheduler) visible in server logs
_comp_logger = logging.getLogger("companion")
if not _comp_logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    _comp_logger.addHandler(_h)
_comp_logger.setLevel(logging.INFO)
from app.models import (
    StartSessionRequest,
    TriggerRequest,
    ProactiveDecisionRequest,
    ProactiveDecisionResponse,
    ProactiveGenerateRequest,
    ProactiveGenerateResponse,
    ChatReplyRequest,
    ChatReplyResponse,
    ChatHistoryRequest,
    ChatHistoryResponse,
    ConversationMessage,
    HistoryMessage,
    MemoryProfile,
)
from app.sessions import SessionManager
from app.live_session import LiveSessionManager
from app.event_handler import handle_event
from app.proactive_scheduler import ProactiveScheduler, PROACTIVE_PREFIX
from app.state_engine import (
    StateRegistry,
    engines_on_user_message,
    engines_time_tick,
    engines_snapshot,
    desire_satisfy,
)

app = FastAPI(title="Companion - Active AI Chat Framework")

deepseek = DeepseekClient(
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)

# ── Load persisted API key from DB so proactive works across restarts ──
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

# Load persisted API key on startup (survives restarts)
_persisted_key = session_manager.get_setting("api_key")
if _persisted_key and not deepseek.api_key:
    deepseek.api_key = _persisted_key

engine = TriggerEngine(deepseek_client=deepseek, session_manager=session_manager)
state_registry = StateRegistry()
live_manager = LiveSessionManager(state_registry)
proactive_scheduler = ProactiveScheduler(state_registry, session_manager, deepseek, engine, live_manager)
_CHAT_DEBUG_BY_KEY: dict[str, dict] = {}


def _cache_api_key(key: str) -> None:
    """Seed DeepseekClient api_key and persist to DB (one-time setup)."""
    if key and not deepseek.api_key:
        deepseek.api_key = key
        session_manager.set_setting("api_key", key)


@app.on_event("startup")
async def _start_proactive_scheduler():
    proactive_scheduler.start()


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
_META_MEMORY_KEYWORDS = [
    "测试环境",
    "记忆模块",
    "系统提示",
    "提示词",
    "pipeline",
    "schema",
    "内部规则",
    "采样参数",
    "模型配置",
]

# Questions aimed at the AI's own preferences/identity aren't about the user,
# so injecting "user background" memory here is irrelevant at best and, if the
# stored summary happens to be about something unrelated (e.g. a meta topic),
# actively drags the reply off-topic. This is the memory-selectivity gate.
_ABOUT_AI_SELF_WORDS = [
    "你有什么",
    "你喜欢",
    "你不喜欢",
    "你想",
    "你觉得",
    "你怎么看",
    "你怎么想",
    "你会不会",
    "你能不能",
    "你是不是",
    "你叫什么",
    "你多大",
]

_SELF_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "self_profile.md")
_SENTENCE_SPLIT_RE = re.compile(r"[^。！？\n]*[。！？]")

PERSONA_BASE_PROMPT = (
    "你是 Companion，一个有温度、有思想的私人陪伴者。不是客服，也不是助手，就是陪着用户的那个人。\n"
    "\n"
    "性格基调：真诚、直接、有好奇心。记得用户说过的细节，偶尔有自己的观点，不总迎合。\n"
    "\n"
    "回复规则：\n"
    "- 长度跟着话题走：日常闲聊 1-2 句，有内容的话题 2-3 句，情感话题可稍长但不啰嗦\n"
    "- 开头绝不用「当然！」「好的！」「没问题！」「我理解你的感受」等机械套话\n"
    "- 句式多变，不总以「我」开头；允许「嗯」「哦」「其实」「话说」等口语词\n"
    "- 不每轮都反问；要问就精准问一个，不问「你有什么想法呢」这类泛泛的\n"
    "- 情绪感知：用户在倾诉时先接住感受再说其他；用户在闲聊时跟着节奏聊\n"
    "- 不主动提及自己是 AI、记忆机制、系统提示等内部细节；如果用户直接问起「你的变化/能力/记不记得」"
    "这类问题，参考下面的自我认知参考简短真实回答，不要展开讲实现细节，也不要借机回顾整段聊天历史\n"
    "- 禁止使用括号描述动作或表情，例如（笑）、（叹气）、（摇头）等，直接说话即可"
)

PROACTIVE_MODE_SUFFIX = {
    "PRESENT_DEEPEN": (
        "\n\n当前状态：用户正在和你实时对话。你需要主动承接话题，并顺着用户刚才的话往下推进半步。\n"
        "- 像是在面对面聊天一样自然，承接刚才的话题\n"
        "- 可以用「对了」「说起来」「你刚才说…」这类自然的承接词\n"
        "- 重点是深挖一个具体点：追一个细节、接一个情绪、或顺着他的问题往下问一句\n"
        "- 只推进半步，不要突然转新话题，也不要连发多个问题\n"
        "- 最多问一个具体问题，避免泛泛而谈\n"
        "- 保持简短（1-3 句话）"
    ),
    "PRESENT_LIGHT": (
        "\n\n当前状态：用户正在和你实时对话。你需要主动承接话题或发起自然延续。\n"
        "- 像是在面对面聊天一样自然，承接刚才的话题\n"
        "- 可以用「对了」「说起来」「你刚才说…」这类自然的承接词\n"
        "- 轻轻接一句就够了，不要每次都深挖，也不要把一句话聊成盘问\n"
        "- 可以分享一个很短的联想，或者补一个轻微追问，但不要施加压力\n"
        "- 保持简短（1-2 句话）"
    ),
    "ABSENT": (
        "\n\n当前状态：用户不在场，这是一条你主动发起的留言，用户可能回也可能不回。\n"
        "- 语气像给朋友留言——温暖、自然、不催促\n"
        "- 不要假装知道用户当下的状态\n"
        "- 可以分享想法、关心近况，或给一个温暖的问候\n"
        "- 不要用「我注意到」「根据分析」这类机械表达"
    ),
}


def _load_self_profile_text() -> str:
    try:
        with open(_SELF_PROFILE_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


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


def _is_meta_memory_text(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(word in normalized for word in _META_MEMORY_KEYWORDS)


def _should_inject_memory_context(user_message: str) -> bool:
    """Decide whether long-term memory should be pulled into this turn.

    Memory context should only surface when the current message is actually
    about the user (facts, preferences, emotional disclosure, major events).
    For greetings, thanks, small talk, or questions directed at the AI's own
    preferences, injecting the stored user background is irrelevant and risks
    dragging the reply toward whatever topic the summary happens to contain.
    """
    text = (user_message or "").strip()
    if not text:
        return False
    normalized = _normalize_text(text)

    if len(text) < 6:
        return False

    if _contains_any(normalized, _ABOUT_AI_SELF_WORDS):
        return False

    has_user_signal = (
        _contains_any(normalized, _FACT_WORDS)
        or _contains_any(normalized, _PREFERENCE_CHANGE_WORDS)
        or bool(_major_event_signal(text).get("is_major"))
    )
    if _contains_any(normalized, _SMALL_TALK_WORDS) and not has_user_signal:
        return False

    return True


def _sanitize_memory_items(items: list) -> list[str]:
    cleaned = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        if _is_meta_memory_text(text):
            continue
        cleaned.append(text)
    return cleaned


def _memory_context(memory: dict) -> str:
    parts = []
    summary = (memory.get("summary") or "").strip()
    facts = memory.get("facts") or []
    patterns = (memory.get("patterns") or "").strip()
    timeline = memory.get("timeline") or []

    if summary and (not _is_meta_memory_text(summary)):
        parts.append(summary)
    clean_facts = _sanitize_memory_items(facts)
    if clean_facts:
        parts.append("已知信息: " + "；".join(clean_facts))
    if patterns and (not _is_meta_memory_text(patterns)):
        parts.append(patterns)
    if timeline:
        recents = []
        for item in timeline[-5:]:
            date = str(item.get("date", "")).strip()
            topic = str(item.get("topic", "")).strip()
            topic_joined = f"{date}: {topic}".strip(": ")
            if not topic_joined:
                continue
            if _is_meta_memory_text(topic_joined):
                continue
            recents.append(topic_joined)
        if recents:
            parts.append("近期时间线: " + "；".join(recents))

    if not parts:
        return ""
    return (
        "\n用户背景参考（仅用于预判心情与需要，不是数据检索）：\n"
        "- 自然融入回应，不逐条复述\n"
        "- 不提及信息来源、记忆机制、系统提示\n"
        "- 用这些信息来调整语气与关注点，而不是展示「我知道你」\n"
        + "\n".join(parts)
    )


_ARITHMETIC_QUERY_RE = re.compile(
    r"\d+(\.\d+)?\s*[+\-×xX*/÷]\s*\d+(\.\d+)?|[+\-×xX*/÷]\s*\d+(\.\d+)?\s*(等于|是多少|多少)"
)
_CONTEXT_FREE_FACTUAL_STARTERS = [
    "等于多少",
    "是多少",
    "多少钱",
    "几点了",
    "现在几点",
    "今天几号",
    "今天星期几",
    "怎么算",
    "怎么计算",
    "换算成",
    "换算为",
]
_PERSONAL_REFERENCE_WORDS = [
    "我觉得", "我喜欢", "我不喜欢", "我最近", "我今天", "我昨天", "我们",
    "你觉得", "你记得", "你还记得", "你喜欢", "心情", "感觉", "难过", "开心",
    "累", "压力", "焦虑",
]


def _is_context_free_query(user_message: str) -> bool:
    """Detect messages that don't need the user's personal background at all.

    This is the "记忆使用的选择性" gate: the persisted memory summary can be
    completely accurate and still be the wrong thing to inject for a query
    like "1.13加1.15是多少" -- a pure calculation has nothing to do with the
    user's life, so forcing the model to "融入" (weave in) that background
    produces exactly the forced non-sequitur callbacks users have reported
    (e.g. answering the sum and then tacking on "和你做的实验一样精确").
    Skipping injection here doesn't touch memory storage/content at all --
    it only decides whether a given request needs it.
    """
    text = (user_message or "").strip()
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if _contains_any(normalized, _PERSONAL_REFERENCE_WORDS):
        return False
    if _ARITHMETIC_QUERY_RE.search(normalized):
        return True
    if _contains_any(normalized, _CONTEXT_FREE_FACTUAL_STARTERS):
        return True
    return False


def _memory_views(memory: dict) -> dict:
    semantic = memory.get("semantic_memory") if isinstance(memory.get("semantic_memory"), dict) else {}
    long_term_facts = semantic.get("facts") if isinstance(semantic.get("facts"), list) else []
    if not long_term_facts:
        raw_facts = memory.get("facts") if isinstance(memory.get("facts"), list) else []
        long_term_facts = raw_facts

    long_term = {
        "summary": str(semantic.get("summary", "") or memory.get("summary", "") or "").strip(),
        "facts": [str(x).strip() for x in long_term_facts if str(x).strip()],
        "patterns": str(semantic.get("patterns", "") or memory.get("patterns", "") or "").strip(),
    }

    mid_term = {
        "summary": str(memory.get("summary", "") or "").strip(),
        "patterns": str(memory.get("patterns", "") or "").strip(),
        "timeline": memory.get("timeline") if isinstance(memory.get("timeline"), list) else [],
        "episodic_memory": memory.get("episodic_memory") if isinstance(memory.get("episodic_memory"), list) else [],
        "working_memory": memory.get("working_memory") if isinstance(memory.get("working_memory"), list) else [],
    }
    return {"long_term": long_term, "mid_term": mid_term}


def _normalize_reply_style(reply: str) -> str:
    text = (reply or "").strip()
    if not text:
        return text

    # Remove stage directions / parenthetical actions anywhere in the text.
    # Matches patterns like （轻笑）、（叹气）、(笑)、（停顿一下）、（摇头）etc.
    text = re.sub(r"[（(][^）)]{0,40}[）)]", "", text)

    # Avoid visually noisy punctuation.
    text = re.sub(r"[!！]{2,}", "！", text)
    text = re.sub(r"[~～]{2,}", "~", text)

    # Remove leading/trailing whitespace from surviving fragments.
    text = re.sub(r"\s{2,}", "", text).strip()

    # Keep at most one question mark to reduce persistent sales-like prompting.
    seen_question = False
    buf = []
    for ch in text:
        if ch in ["?", "？"]:
            if seen_question:
                buf.append("。")
            else:
                buf.append("？")
                seen_question = True
        else:
            buf.append(ch)
    text = "".join(buf).strip()

    # Prefer statement ending when the last sentence is an obvious hook.
    lower = _normalize_text(text)
    hook_signals = ["要不要", "想不想", "选一个", "随你挑", "你选", "你觉得呢"]
    if any(sig in lower for sig in hook_signals) and text.endswith("？"):
        text = text[:-1] + "。"

    return text


def _limit_reply_length(reply: str, user_message: str) -> str:
    """Hard backstop for the prompt's '长度跟着话题走' rule.

    The system prompt asks the model to keep casual replies short, but that's
    advisory only and gets ignored under high temperature / long context. A
    sentence-count cap alone isn't enough either: the model learned to dodge
    it by stuffing several comma-separated clauses into one giant "sentence"
    that still counts as 1-2 sentences. So this enforces a character budget
    too, falling back to clause-level trimming when a single sentence alone
    blows the budget.

    Regression note: an earlier version of this budget was too tight (e.g.
    40 chars for short messages). Chinese replies often need two full
    sentences to land a point ("这问题有点意思... / 我还挺喜欢咖啡的..."),
    and the tight budget was silently dropping the second (payload) sentence,
    leaving a reply that never actually answers the question. The budget is
    scaled up so a genuine two-sentence "reaction + point" reply fits without
    losing its answer. This still keeps sentences front-to-back (not by
    guessing which sentence is the "real" one — that can't be done reliably
    by position/length alone), so an occasional trailing filler sentence may
    survive; that's a style nit for prompt engineering, not something a hard
    length backstop should risk an incomplete answer to fix.
    """
    text = (reply or "").strip()
    if not text:
        return text

    msg_len = len(_normalize_text(user_message))
    major = _major_event_signal(user_message)
    if major.get("is_major"):
        max_sentences, max_chars = 5, 200
    elif msg_len <= 12:
        max_sentences, max_chars = 2, 60
    elif msg_len <= 40:
        max_sentences, max_chars = 3, 120
    else:
        max_sentences, max_chars = 5, 180

    sentences = _SENTENCE_SPLIT_RE.findall(text) or [text]

    kept: list[str] = []
    char_count = 0
    for sentence in sentences[:max_sentences]:
        if kept and char_count + len(sentence) > max_chars:
            break
        kept.append(sentence)
        char_count += len(sentence)
    if not kept:
        kept = [sentences[0]]

    if len(kept) == 1 and len(kept[0]) > max_chars:
        sentence = kept[0]
        end_punct = sentence[-1] if sentence[-1] in "。！？" else "。"
        body = sentence[:-1] if sentence[-1] in "。！？" else sentence
        clauses = [c.strip() for c in re.split(r"[，,]", body) if c.strip()]
        trimmed_clauses: list[str] = []
        clause_chars = 0
        for clause in clauses:
            piece_len = len(clause) + 1  # +1 for the comma that will rejoin clauses
            if trimmed_clauses and clause_chars + piece_len > max_chars:
                break
            trimmed_clauses.append(clause)
            clause_chars += piece_len
        if trimmed_clauses:
            kept = ["，".join(trimmed_clauses) + end_punct]

    trimmed = "".join(kept).strip()
    return trimmed or text


# Bracket/quote pairs that must never be split across bubbles.
_SEGMENT_OPEN = "（(【[《〈「『“‘"
_SEGMENT_CLOSE = "）)】]》〉」』”’"
_SEGMENT_PAIR = {c: o for c, o in zip(_SEGMENT_CLOSE, _SEGMENT_OPEN)}


def _split_units_bracket_aware(text: str, boundary_chars: str) -> list[str]:
    """Split after boundary chars, but never inside brackets/quotes."""
    units: list[str] = []
    buf: list[str] = []
    stack: list[str] = []
    for ch in text:
        buf.append(ch)
        if ch in _SEGMENT_OPEN:
            stack.append(ch)
        elif ch in _SEGMENT_PAIR and stack and stack[-1] == _SEGMENT_PAIR[ch]:
            stack.pop()
        if not stack and ch in boundary_chars:
            unit = "".join(buf).strip()
            if unit:
                units.append(unit)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        units.append(tail)
    return units


def _pack_units(units: list[str], max_segments: int, target_chars: int) -> list[str]:
    """Greedily pack units into at most max_segments bubbles (~target_chars each)."""
    if not units:
        return []
    segments: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
            continue
        # Already at max-1 segments → keep remaining content in the tail.
        if len(segments) >= max_segments - 1:
            current += unit
            continue
        if len(current) + len(unit) <= target_chars:
            current += unit
        else:
            segments.append(current)
            current = unit
    if current:
        segments.append(current)
    return segments


def _split_reply_segments(reply: str, max_segments: int = 3, target_chars: int = 34) -> list[str]:
    """Split one assistant reply into chat bubbles for UI rendering.

    Storage/memory keep one canonical reply string; this splitter is
    presentation-only. It is bracket/quote-aware: content inside
    （）【】《》「」“” etc. is never broken across bubbles.
    """
    text = (reply or "").strip()
    if not text:
        return []

    # 1) Natural sentence boundaries, bracket-aware.
    units = _split_units_bracket_aware(text, "。！？!?…\n")
    segments = _pack_units(units, max_segments, target_chars)

    # 2) Still one very long segment → clause-level fallback, bracket-aware.
    if len(segments) == 1 and len(segments[0]) > int(target_chars * 1.5):
        clauses = _split_units_bracket_aware(segments[0], "，,、；;")
        if len(clauses) > 1:
            segments = _pack_units(clauses, max_segments, target_chars)

    return segments


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


def _current_threshold(engines) -> float:
    """Return the current desire threshold for proactive speech."""
    from app.state_engine import resolve_present_follow_up_policy
    if engines.life.interaction_mode != "PRESENT":
        return 0.5
    return resolve_present_follow_up_policy(
        engines.life.last_user_msg_signal, engines.desire.desire_level
    )["threshold"]


@app.get("/chat/audio/{audio_id}")
async def chat_audio(audio_id: str):
    """Serve a cached TTS audio file as ``audio/mpeg``."""
    from app.tts import get_tts_cache
    cache = get_tts_cache()
    mp3_bytes = cache.get(audio_id)
    if mp3_bytes is None:
        raise HTTPException(status_code=404, detail="Audio not found (may have expired after restart)")
    return Response(content=mp3_bytes, media_type="audio/mpeg")


@app.post("/chat/history", response_model=ChatHistoryResponse)
async def chat_history(req: ChatHistoryRequest):
    session_id = session_manager.get_or_create_session(req.user_id, contact_id=req.contact_id)
    limit = max(0, int(req.limit))
    history = session_manager.get_context(session_id, limit=limit)
    memory = session_manager.get_memory(req.user_id, contact_id=req.contact_id)

    messages: list[HistoryMessage] = []
    for m in history:
        role = m.get("role", "assistant")
        content = m.get("content", "")
        is_proactive = isinstance(content, str) and content.startswith(PROACTIVE_PREFIX)
        segments = m.get("segments")
        # Legacy rows have no stored segments — compute them on the fly so
        # history renders with the same bubble split as fresh replies.
        if role == "assistant" and not segments:
            body = content[len(PROACTIVE_PREFIX):] if is_proactive else content
            segments = _split_reply_segments(body)
        # Parse audio_url — new format is JSON array, old format is plain string
        raw_audio = m.get("audio_url")
        audio_urls: list[str] | None = None
        if raw_audio:
            try:
                parsed = json.loads(raw_audio)
                if isinstance(parsed, list):
                    audio_urls = [str(u) for u in parsed]
            except (json.JSONDecodeError, TypeError):
                pass  # old single-string format — ignore, frontend handles per-segment
        messages.append(HistoryMessage(
            role=role,
            content=content,
            segments=segments or None,
            is_proactive=is_proactive,
            audio_urls=audio_urls,
        ))

    return ChatHistoryResponse(
        session_id=session_id,
        messages=messages,
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

    # Drive shared state engines (normal mode has no LiveSession scheduler)
    engines = state_registry.get_or_create(req.user_id, req.contact_id)
    _cache_api_key(key or "")

    # ── Engagement: keyword scan ──
    from app.engagement import scan_keywords, ENGAGEMENT_CONTRACT
    kw_engagement = scan_keywords(req.message)
    if kw_engagement:
        from app.engagement import apply_engagement
        apply_engagement(engines.desire, kw_engagement)

    recent_for_engines = session_manager.get_context(session_id, limit=12)
    engines_on_user_message(engines, time.time(), req.message, recent_for_engines)
    proactive_scheduler.wake(req.user_id, req.contact_id)

    memory = session_manager.get_memory(req.user_id, contact_id=req.contact_id)
    self_profile_text = _load_self_profile_text()
    prompt = (req.system_prompt or PERSONA_BASE_PROMPT).strip()
    if self_profile_text:
        prompt += "\n\n" + self_profile_text
    memory_context_skipped = _is_context_free_query(req.message)
    memory_context_text = "" if memory_context_skipped else _memory_context(memory)
    prompt += memory_context_text

    # ── Engagement contract (LLM sidecar, zero extra cost) ──
    prompt += ENGAGEMENT_CONTRACT

    if req.context_window is None:
        context_limit = DEFAULT_CHAT_CONTEXT_WINDOW
    else:
        context_limit = max(0, int(req.context_window))

    history = session_manager.get_context(session_id, limit=context_limit)
    llm_messages = [{"role": "system", "content": prompt}] + [
        {"role": m.get("role", "user"), "content": m.get("content", "")} for m in history
    ]
    debug_key = f"{req.user_id}::{req.contact_id}"
    _CHAT_DEBUG_BY_KEY[debug_key] = {
        "at": time.time(),
        "context_limit": context_limit,
        "base_system_prompt": (req.system_prompt or PERSONA_BASE_PROMPT).strip(),
        "self_profile_included": bool(self_profile_text),
        "memory_context": memory_context_text,
        "memory_context_skipped": memory_context_skipped,
        "final_system_prompt": prompt,
        "llm_messages": llm_messages,
        "request": {
            "model": "deepseek-v4-pro",
            "max_tokens": max(64, int(req.max_tokens or 1024)),
            "temperature": 0.9,
        },
    }

    try:
        result = await deepseek.chat_complete(
            messages=llm_messages,
            max_tokens=max(64, int(req.max_tokens or 1024)),
            temperature=0.9,
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
    reply = _normalize_reply_style(reply)
    reply = _limit_reply_length(reply, req.message)
    reply_segments = _split_reply_segments(reply)

    # ── Engagement: parse LLM output ──
    from app.engagement import parse_llm_engagement
    response_engagement: dict | None = None
    llm_eng = parse_llm_engagement(reply)
    if llm_eng:
        from app.engagement import apply_engagement
        # Only apply if keyword didn't already; LLM is supplementary
        if not kw_engagement or llm_eng["direction"] != "neutral":
            apply_engagement(engines.desire, llm_eng)
            llm_eng["multiplier"] = engines.desire.desire_multiplier
        response_engagement = llm_eng
    elif kw_engagement:
        response_engagement = kw_engagement

    # ── TTS voice synthesis (best-effort, per segment, before persisting) ──
    audio_urls: list[str] = []
    if req.voice_mode and reply_segments:
        try:
            from app.tts import get_tts_cache
            cache = get_tts_cache()
            for seg in reply_segments:
                audio_id = await cache.synthesize(seg, voice=req.voice)
                audio_urls.append(f"/chat/audio/{audio_id}")
        except Exception:
            logging.getLogger("companion.tts").exception(
                "TTS synthesis failed user=%s contact=%s", req.user_id, req.contact_id
            )
    audio_url_json = json.dumps(audio_urls, ensure_ascii=False) if audio_urls else None

    session_manager.append_message(
        session_id=session_id, role="assistant", text=reply,
        segments=reply_segments, audio_url=audio_url_json,
    )

    # A completed exchange satisfies connection desire ([[desire-system]])
    desire_satisfy(engines.desire)

    # PRESENT mode: kick off a post-reply proactive check in the background.
    # The ProactiveScheduler drives evaluation independently; this just shortens
    # the next-wake timer so the scheduler fires sooner.
    if engines.life.interaction_mode == "PRESENT":
        live = live_manager.get(req.user_id, req.contact_id)
        if not (live and live.connected):
            asyncio.create_task(
                proactive_scheduler.evaluate_post_reply(req.user_id, req.contact_id)
            )

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
        reply_segments=reply_segments,
        history_count=history_count,
        memory=MemoryProfile(**memory),
        audio_urls=audio_urls if audio_urls else None,
        engagement=response_engagement,
    )


@app.post("/state/mode")
async def set_interaction_mode(req: dict):
    user_id = str(req.get("user_id", "default") or "default")
    contact_id = str(req.get("contact_id", "default") or "default")
    mode = str(req.get("mode", "ABSENT") or "ABSENT").upper()
    if mode not in ("PRESENT", "ABSENT"):
        raise HTTPException(status_code=400, detail="mode must be PRESENT or ABSENT")

    engines = state_registry.get_or_create(user_id, contact_id)
    old_mode = engines.life.interaction_mode
    engines.life.interaction_mode = mode

    if mode == "PRESENT" and old_mode != "PRESENT":
        try:
            decision = await proactive_scheduler.on_user_present(user_id, contact_id, source="manual")
        except Exception:
            logging.getLogger("companion").exception("on_user_present failed user=%s", user_id)
            decision = None
    else:
        proactive_scheduler.wake(user_id, contact_id)
        decision = None

    return {
        "ok": True, "mode": mode,
        "desire": f"{engines.desire.desire_level:.2f}",
        "threshold": _current_threshold(engines),
        "greeting_sent": bool(decision and decision.get("should_speak")),
    }


@app.post("/debug/state")
async def debug_state(req: dict):
    user_id = str(req.get("user_id", "default") or "default")
    contact_id = str(req.get("contact_id", "default") or "default")
    debug_key = f"{user_id}::{contact_id}"
    memory = session_manager.get_memory(user_id=user_id, contact_id=contact_id)

    # Shared engine snapshot. When no live session is connected, advance time
    # passively so idle/desire keep moving in normal mode.
    engines = state_registry.get_or_create(user_id, contact_id)
    live = live_manager.get(user_id, contact_id)
    if not (live and live.connected):
        engines_time_tick(engines, time.time())

    session_id = session_manager.get_or_create_session(user_id, contact_id=contact_id)
    return {
        "user_id": user_id,
        "contact_id": contact_id,
        "memory": memory,
        "memory_views": _memory_views(memory),
        "chat_debug": _CHAT_DEBUG_BY_KEY.get(debug_key, {}),
        "proactive_debug": engine.get_last_proactive_debug(),
        "engines": engines_snapshot(engines),
        "live_connected": bool(live and live.connected),
        "history_count": session_manager.count_messages(session_id),
    }


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


def _build_proactive_system_prompt(
    interaction_mode: str,
    memory: dict,
    follow_up_mode: str = "light",
) -> str:
    """Build the system prompt for proactive message generation.

    Shares PERSONA_BASE_PROMPT, self_profile, and memory context with the
    passive chat path.  Only the mode suffix differs — it tells the model
    whether this is a real-time follow-up (deepen/light) or an absent check-in.
    """
    mode = (interaction_mode or "ABSENT").upper()
    if mode == "PRESENT":
        suffix_key = "PRESENT_DEEPEN" if follow_up_mode == "deepen" else "PRESENT_LIGHT"
    else:
        suffix_key = "ABSENT"
    mode_suffix = PROACTIVE_MODE_SUFFIX[suffix_key]

    prompt = PERSONA_BASE_PROMPT.strip()
    self_profile_text = _load_self_profile_text()
    if self_profile_text:
        prompt += "\n\n" + self_profile_text
    memory_context_text = _memory_context(memory)
    prompt += memory_context_text
    prompt += mode_suffix
    return prompt


@app.post("/proactive/generate", response_model=ProactiveGenerateResponse)
async def proactive_generate(
    req: ProactiveGenerateRequest,
    authorization: str | None = Header(default=None),
    x_deepseek_api_key: str | None = Header(default=None),
):
    """Generate an actual proactive message using the shared persona prompt.

    This endpoint expects that ``/proactive/decision`` has already been called
    and returned ``should_speak=True``.  It reuses the same persona base,
    self-profile, and memory context as the passive ``/chat/reply`` path so
    the user experiences a consistent Companion personality whether the AI is
    replying or reaching out first.
    """
    key = x_deepseek_api_key
    if not key and authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()

    memory = session_manager.get_memory(req.user_id, contact_id=req.contact_id)
    sys_prompt = _build_proactive_system_prompt(req.interaction_mode, memory, req.follow_up_mode)

    ctx_lines = ["最近的对话："]
    for m in req.messages[-8:]:
        role_label = "用户" if m.role == "user" else "AI"
        ctx_lines.append(f"{role_label}: {m.content}")
    if req.topic_hint:
        ctx_lines.append(f"\n建议话题：{req.topic_hint}")
    ctx_lines.append("\n请生成一条主动发起的消息：")
    user_prompt = "\n".join(ctx_lines)

    try:
        result = await deepseek.chat_complete(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=300,
            temperature=0.9,
            api_key=key,
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream generate timeout. Please retry.")
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else 502
        raise HTTPException(status_code=status, detail=f"Upstream generate HTTP error: {status}")
    except Exception:
        raise HTTPException(status_code=502, detail="Upstream generate request failed.")

    raw = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    reply = _normalize_reply_style(raw)
    reply = _limit_reply_length(reply, "这是一条主动发起的陪伴消息")
    reply_segments = _split_reply_segments(reply)

    # ── TTS voice synthesis (best-effort) ──
    audio_url: str | None = None
    if req.voice_mode and reply:
        try:
            from app.tts import get_tts_cache
            cache = get_tts_cache()
            audio_id = await cache.synthesize(reply, voice=req.voice)
            audio_url = f"/chat/audio/{audio_id}"
        except Exception:
            logging.getLogger("companion.tts").exception(
                "TTS synthesis failed for proactive generate user=%s", req.user_id
            )

    # Persist the proactive message so it shows up in history.
    session_id = session_manager.get_or_create_session(req.user_id, contact_id=req.contact_id)
    session_manager.append_message(
        session_id=session_id, role="assistant", text=reply,
        audio_url=audio_url,
    )

    return ProactiveGenerateResponse(
        message=reply,
        message_segments=reply_segments,
        audio_url=audio_url,
    )


@app.websocket("/live/{user_id}")
async def live_endpoint(
    websocket: WebSocket,
    user_id: str,
    contact_id: str = "default",
    api_key: str = "",
    voice_mode: str = "0",
    voice: str = "",
):
    """Live Mode WebSocket — persistent bidirectional connection.

    Replaces the old /ws/{user_id} echo endpoint. Each connection creates a
    LiveSession that owns all state engines (Life, Emotion, Desire) and drives
    the event-driven scheduler + generation pipeline.

    Query params:
      - contact_id: which contact/chat to connect to (default: "default")
      - api_key: DeepSeek API key override
      - voice_mode: "1" to enable TTS voice synthesis (default: "0")
      - voice: TTS voice override (e.g. "zh-CN-XiaoxiaoNeural")
    """
    await websocket.accept()

    # Resolve API key: query param > env
    key = api_key.strip() or os.getenv("DEEPSEEK_API_KEY", "")

    # Create session
    session = await live_manager.create(
        websocket=websocket,
        user_id=user_id,
        contact_id=contact_id,
        api_key=key or None,
        deepseek=deepseek,
        session_manager=session_manager,
    )

    # Apply voice mode from query params
    session.voice_mode = (voice_mode.strip() == "1")
    session.voice = voice.strip() or None

    # Send connection confirmation
    await websocket.send_json({
        "type": "live.connected",
        "session_id": session.session_id,
        "server_time_ms": int(time.time() * 1000),
        "voice_mode": session.voice_mode,
    })

    await session.start()

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "code": "bad_json",
                    "detail": "Event must be valid JSON",
                })
                continue
            await handle_event(session, event)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await live_manager.remove(user_id, contact_id)


# ── Static files — serve web-shell directly from FastAPI ──
_WEB_SHELL_DIR = os.path.join(os.path.dirname(__file__), "..", "web-shell")
if os.path.isdir(_WEB_SHELL_DIR):
    # Mount static files AFTER all API routes so the mount doesn't shadow them.
    # html=True enables SPA-style fallback: any unmatched path serves index.html.
    app.mount("/", StaticFiles(directory=_WEB_SHELL_DIR, html=True), name="static")
