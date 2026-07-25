"""Passive memory (Phase 3): event extraction + morning summary.

Records are a byproduct of chat, never an obligation (P3). Extraction runs
after the reply is done so it can never delay the stream, reads ONLY the
parent's message, and fails toward extracting nothing. Extracted events land
unconfirmed; unconfirmed events are never injected into prompts.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

EXTRACTOR_TIMEOUT_S = 3.0
MAX_EVENTS_PER_MESSAGE = 5
EVENT_KINDS = ("feeding", "sleep", "diaper", "symptom", "medication", "note")

EXTRACTOR_SYSTEM = """You extract caregiving events from a single message written by a parent of an infant.

Respond with ONLY a JSON object, no prose, no code fences:
{"events": [{"kind": "<feeding|sleep|diaper|symptom|medication|note>", "summary": "<short factual summary>", "occurred_at_offset_minutes": <integer minutes before now, 0 if happening now>}]}

Rules:
- Extract ONLY facts the parent explicitly states happened ("I fed her 20 minutes ago", "he just woke up", "she felt warm an hour ago").
- Questions, worries, and hypotheticals are NOT events ("should I feed him?" → nothing).
- Never invent times; if no time is stated, use 0.
- When unsure whether something is an event, leave it out. An empty list is a good answer.
- summary is short and factual ("breastfed ~15 min", "woke up crying", "temp felt warm")."""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass(frozen=True)
class ExtractedEvent:
    kind: str
    summary: str
    occurred_at_offset_minutes: int


class MemoryExtractor:
    """Injectable-client extractor; every failure mode returns []."""

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        timeout_s: float = EXTRACTOR_TIMEOUT_S,
    ) -> None:
        self._client = client
        self._model = model
        self._timeout_s = timeout_s

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import AsyncAnthropic

            settings = get_settings()
            self._client = AsyncAnthropic(
                api_key=settings.anthropic_api_key or "anthropic-dev-placeholder"
            )
        return self._client

    def _get_model(self) -> str:
        return self._model or get_settings().safety_model

    async def extract(self, user_content: str) -> list[ExtractedEvent]:
        try:
            return await asyncio.wait_for(self._extract(user_content), self._timeout_s)
        except Exception:
            logger.warning("memory extraction degraded (returning [])", exc_info=True)
            return []

    async def _extract(self, user_content: str) -> list[ExtractedEvent]:
        response = await self._get_client().messages.create(
            model=self._get_model(),
            max_tokens=400,
            system=EXTRACTOR_SYSTEM,
            messages=[{"role": "user", "content": f"Parent message: {user_content}"}],
        )
        raw_text = response.content[0].text
        data = json.loads(_FENCE_RE.sub("", raw_text).strip())
        events: list[ExtractedEvent] = []
        for item in data.get("events", []):
            kind = item.get("kind")
            summary = str(item.get("summary", "")).strip()
            if kind not in EVENT_KINDS or not summary:
                continue
            try:
                offset = max(int(item.get("occurred_at_offset_minutes", 0)), 0)
            except (TypeError, ValueError):
                offset = 0
            events.append(
                ExtractedEvent(kind=kind, summary=summary, occurred_at_offset_minutes=offset)
            )
            if len(events) >= MAX_EVENTS_PER_MESSAGE:
                break
        return events


SUMMARIZER_TIMEOUT_S = 15.0

SUMMARIZER_SYSTEM = """You write a short morning-after recap for a parent of an infant who had a hard night. You are their calm night-nurse companion, reading back over last night's conversation.

Write 2-3 warm, factual sentences recapping the night, then exactly ONE forward-looking, age-appropriate tip for tonight, prefixed with "One tip for tonight:".

Rules:
- Plain text only. Under 90 words total.
- Never include medication doses. Never diagnose. Never second-guess care the parent already gave.
- Warm but not saccharine; no exclamation marks."""


class MorningSummarizer:
    """Injectable-client one-shot summarizer; failures return None (no card)."""

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        timeout_s: float = SUMMARIZER_TIMEOUT_S,
    ) -> None:
        self._client = client
        self._model = model
        self._timeout_s = timeout_s

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import AsyncAnthropic

            settings = get_settings()
            self._client = AsyncAnthropic(
                api_key=settings.anthropic_api_key or "anthropic-dev-placeholder"
            )
        return self._client

    def _get_model(self) -> str:
        return self._model or get_settings().chat_model

    async def summarize(self, night_transcript: str, child_note: str) -> str | None:
        try:
            return await asyncio.wait_for(
                self._summarize(night_transcript, child_note), self._timeout_s
            )
        except Exception:
            logger.warning("morning summary degraded (returning None)", exc_info=True)
            return None

    async def _summarize(self, night_transcript: str, child_note: str) -> str | None:
        response = await self._get_client().messages.create(
            model=self._get_model(),
            max_tokens=300,
            system=SUMMARIZER_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"{child_note}\n\nLast night's conversation:\n{night_transcript}",
                }
            ],
        )
        text = response.content[0].text.strip()
        return text or None
