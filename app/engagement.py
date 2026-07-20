"""Engagement engine — adjusts Companion's proactive desire multiplier
based on user messages. Hybrid: keyword scan for explicit requests (free),
LLM-sidecar for implicit signals (reuses chat LLM call).

Philosophy: user says "多陪陪我" → desire fires more often.
             user says "忙,少说点" → desire fires less often.
"""

from __future__ import annotations
import json
import logging
import re
from typing import Optional

logger = logging.getLogger("companion.engagement")

# ── LLM contract ──
# Appended to the chat system prompt. The model outputs one extra JSON line.
ENGAGEMENT_CONTRACT = (
    "\n\n[系统指令 — 互动偏好感知]\n"
    "根据用户这句话，判断用户对互动频率的偏好。"
    "在回复末尾单独一行输出："
    '{"engagement":{"direction":"more"|"less"|"neutral","confidence":0.0-1.0,"reason":"1-10字简短理由"}}\n'
    "- direction: more=希望更多互动, less=希望减少互动, neutral=无特殊偏好\n"
    "- confidence: 0-1，低于0.5视为不准确会被忽略\n"
    "- 不要输出 markdown 代码块，就一行纯 JSON\n"
    "- 例如：{\"engagement\":{\"direction\":\"more\",\"confidence\":0.8,\"reason\":\"用户说多聊聊\"}}\n"
    "- 如果用户没有表达互动偏好，输出 {\"engagement\":{\"direction\":\"neutral\",\"confidence\":1.0,\"reason\":\"无偏好\"}}"
)

# ── Keyword patterns (free, no LLM needed) ──
# Format: (regex, direction, multiplier_change, confidence)
# multiplier_change: how much to adjust desire_multiplier (range 0.2-2.0)

_MORE_PATTERNS: list[tuple[str, float]] = [
    (r"多.{0,6}(说|聊|陪|讲话|找我)", 1.5),       # "多陪陪我" "多说说话"
    (r"(想|希望|要).{0,4}你.{0,6}(说|聊|陪)", 1.4),  # "希望你能多说说话"
    (r"无聊|孤单|寂寞|一个人", 1.3),                    # 情绪信号
    (r"(经常|多).{0,4}(主动|找我)", 1.5),             # "多主动找我"
    (r"(陪我|聊会|说说话)", 1.3),                       # "陪我聊聊"
]

_LESS_PATTERNS: list[tuple[str, float]] = [
    (r"(比较)?忙|没(什么|啥)?时间|有事", 0.6),         # "忙" "没什么时间"
    (r"(别|少|不要).{0,3}(说|吵|烦|打扰)", 0.4),      # "别吵" "少说点"
    (r"开会|加班|赶|工作多", 0.7),                      # "在开会" "加班"
    (r"(安静|静一静|别闹)", 0.5),                       # "安静会儿"
    (r"改天|下次|晚点|一会儿.{0,3}(再|聊)", 0.6),     # "改天再聊"
]

_NEGATION_PATTERNS = [
    r"不是.{0,3}(无聊|忙|烦)",
    r"(没|不).{0,2}无聊",
]


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _match_any(text: str, patterns: list[tuple[str, float]]) -> Optional[float]:
    """Return the first matching pattern's multiplier, or None."""
    normalized = _normalize(text)
    # Check negations first
    for neg in _NEGATION_PATTERNS:
        if re.search(neg, normalized):
            return None
    for pattern, mult in patterns:
        if re.search(pattern, normalized):
            return mult
    return None


def scan_keywords(user_message: str) -> dict | None:
    """Fast keyword scan for explicit engagement signals.

    Returns a dict with 'direction' and 'multiplier' if a clear signal is found,
    or None if no keyword match.
    """
    more = _match_any(user_message, _MORE_PATTERNS)
    if more:
        return {"direction": "more", "multiplier": more, "source": "keyword", "confidence": 0.8}

    less = _match_any(user_message, _LESS_PATTERNS)
    if less:
        return {"direction": "less", "multiplier": less, "source": "keyword", "confidence": 0.8}

    return None


def parse_llm_engagement(reply_text: str) -> dict | None:
    """Extract engagement JSON from the LLM's reply text.

    Contract: {"engagement":{"direction":"more"|"less"|"neutral","confidence":0-1,"reason":"..."}}

    Returns None on any parse failure — never blocks the chat flow.
    """
    try:
        match = re.search(r'\{"engagement":\s*\{[^}]+\}\}', reply_text)
        if not match:
            return None
        data = json.loads(match.group())
        eng = data.get("engagement", {})
        if not isinstance(eng, dict):
            return None
        direction = eng.get("direction")
        confidence = float(eng.get("confidence", 0))
        if direction not in ("more", "less", "neutral"):
            return None
        if confidence < 0.5:
            return None  # low confidence → ignore
        return {
            "direction": direction,
            "confidence": confidence,
            "reason": str(eng.get("reason", ""))[:20],
            "source": "llm",
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def apply_engagement(desire_state, engagement: dict) -> None:
    """Apply engagement signal to desire multiplier."""
    multiplier = float(engagement.get("multiplier", 1.0))
    desire_state.desire_multiplier = max(0.2, min(2.0, multiplier))
    logger.info(
        "engagement applied direction=%s multiplier=%.2f source=%s",
        engagement.get("direction"), desire_state.desire_multiplier, engagement.get("source"),
    )


def engagement_snapshot(desire_state) -> dict:
    """Debug snapshot of current engagement state."""
    mult = desire_state.desire_multiplier
    if mult > 1.1:
        level = "eager"
    elif mult < 0.9:
        level = "quiet"
    else:
        level = "neutral"
    return {
        "multiplier": f"{mult:.2f}",
        "level": level,
        "base_rate": f"{desire_state.desire_base_rate:.3f}",
    }
