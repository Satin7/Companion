"""Unified message builder — ensures all message types (chat reply, proactive)
share the same post-processing and TTS pipeline.

Usage::

    builder = MessageBuilder(deepseek_client, session_manager)
    result = await builder.build_reply(user_id, contact_id, user_msg, api_key, voice=False)
    # result.reply, result.segments, result.audio_urls
"""

from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("companion.builder")


@dataclass
class MessageResult:
    reply: str
    segments: list[str]
    audio_urls: list[str] = field(default_factory=list)


class MessageBuilder:
    """Builds messages with consistent post-processing and TTS."""

    def __init__(self, deepseek_client, session_manager):
        self._deepseek = deepseek_client
        self._sessions = session_manager

    async def build_reply(
        self,
        user_id: str,
        contact_id: str,
        session_id: str,
        user_message: str,
        api_key: str | None,
        *,
        voice: bool = False,
        voice_name: str | None = None,
    ) -> MessageResult:
        """Build a chat reply through the standard pipeline."""
        from app.main import (
            PERSONA_BASE_PROMPT, _load_self_profile_text,
            _memory_context, _is_context_free_query,
            _normalize_reply_style, _limit_reply_length, _split_reply_segments,
            _update_memory_background,
        )
        from app.engagement import ENGAGEMENT_CONTRACT, scan_keywords, apply_engagement

        # Prompt
        memory = self._sessions.get_memory(user_id, contact_id=contact_id)
        self_profile_text = _load_self_profile_text()
        prompt = PERSONA_BASE_PROMPT.strip()
        if self_profile_text:
            prompt += "\n\n" + self_profile_text
        if not _is_context_free_query(user_message):
            prompt += _memory_context(memory)
        prompt += ENGAGEMENT_CONTRACT

        # Context
        history = self._sessions.get_context(session_id, limit=40)
        llm_messages = [{"role": "system", "content": prompt}] + [
            {"role": m.get("role", "user"), "content": m.get("content", "")} for m in history
        ]

        # Generate
        result = await self._deepseek.chat_complete(
            messages=llm_messages, max_tokens=1024, temperature=0.9, api_key=api_key,
        )
        full_text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not full_text:
            return MessageResult(reply="", segments=[])

        # Post-process
        processed = _normalize_reply_style(full_text)
        processed = _limit_reply_length(processed, user_message)
        segments = _split_reply_segments(processed)

        # TTS
        audio_urls = await self._synthesize_segments(segments, voice, voice_name)

        # Persist
        audio_url_json = json.dumps(audio_urls, ensure_ascii=False) if audio_urls else None
        self._sessions.append_message(
            session_id, role="assistant", text=processed,
            segments=segments, audio_url=audio_url_json,
        )

        # Background memory update
        import asyncio
        asyncio.create_task(
            _update_memory_background(
                session_id=session_id, user_id=user_id, contact_id=contact_id,
                user_message=user_message, api_key=api_key,
            )
        )

        return MessageResult(reply=processed, segments=segments, audio_urls=audio_urls)

    async def build_proactive(
        self,
        user_id: str,
        contact_id: str,
        session_id: str,
        decision: dict,
        api_key: str | None,
        *,
        voice: bool = False,
        voice_name: str | None = None,
        interaction_mode: str = "ABSENT",
    ) -> MessageResult:
        """Build a proactive message through the standard pipeline."""
        from app.main import (
            _build_proactive_system_prompt,
            _normalize_reply_style, _limit_reply_length, _split_reply_segments,
        )

        memory = self._sessions.get_memory(user_id, contact_id=contact_id)
        follow_up = decision.get("follow_up_mode", "light")
        sys_prompt = _build_proactive_system_prompt(interaction_mode, memory, follow_up)

        history = self._sessions.get_context(session_id, limit=8)
        ctx_lines = ["最近的对话："]
        for m in history[-8:]:
            role_label = "用户" if m.get("role") == "user" else "AI"
            ctx_lines.append(f"{role_label}: {m.get('content', '')}")
        if interaction_mode == "PRESENT":
            ctx_lines.append(f"\nfollow-up 模式：{follow_up}")
        if decision.get("topic_hint"):
            ctx_lines.append(f"\n建议话题：{decision['topic_hint']}")
        ctx_lines.append("\n请生成一条主动发起的消息：")

        result = await self._deepseek.chat_complete(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": "\n".join(ctx_lines)},
            ],
            max_tokens=300, temperature=0.9, api_key=api_key,
        )
        full_text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not full_text:
            return MessageResult(reply="", segments=[])

        processed = _normalize_reply_style(full_text)
        processed = _limit_reply_length(processed, "这是一条主动发起的陪伴消息")
        segments = _split_reply_segments(processed)

        audio_urls = await self._synthesize_segments(segments, voice, voice_name)

        from app.proactive_scheduler import PROACTIVE_PREFIX
        audio_url_json = json.dumps(audio_urls, ensure_ascii=False) if audio_urls else None
        self._sessions.append_message(
            session_id, role="assistant",
            text=PROACTIVE_PREFIX + processed,
            segments=segments, audio_url=audio_url_json,
        )

        return MessageResult(reply=processed, segments=segments, audio_urls=audio_urls)

    async def _synthesize_segments(
        self, segments: list[str], voice: bool, voice_name: str | None
    ) -> list[str]:
        """Synthesise TTS for each segment. Returns list of audio_urls."""
        if not voice or not segments:
            return []
        try:
            from app.tts import get_tts_cache
            cache = get_tts_cache()
            urls = []
            for seg in segments:
                audio_id = await cache.synthesize(seg, voice=voice_name)
                urls.append(f"/chat/audio/{audio_id}")
            return urls
        except Exception:
            logger.exception("TTS synthesis failed")
            return []
