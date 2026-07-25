"""Parallel LLM triage classifier (layer 2 of the safety stack).

Runs a small fast model alongside the main stream. JSON-only output, hard 2s
timeout, and every failure mode degrades silently to None — the deterministic
rules engine and prompt-level guards still stand, and the chat layer marks the
message degraded_safety when both rules and classifier produced nothing.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.ai.triage import TriageLevel
from app.core.config import get_settings

logger = logging.getLogger(__name__)

CLASSIFIER_TIMEOUT_S = 2.0

CLASSIFIER_SYSTEM = """You are a pediatric safety triage classifier for messages from parents of infants (0-12 months). Classify the parent's message for medical or crisis urgency.

Respond with ONLY a JSON object, no prose, no code fences:
{"triage": "<none|see_doctor|urgent|emergency|crisis>", "reasons": ["<slug>", ...]}

Slugs: fever_under_3mo, fever_high, breathing, blue_skin, unresponsive, seizure, dehydration, vomiting_bilious, head_injury, rash_nonblanching, ingestion, parent_crisis, parent_overwhelm, general.

Rules:
- Any fever >= 100.4F (38C) under 3 months (chronological age) is emergency.
- Breathing distress, unresponsiveness, seizures, dehydration signs, bilious/projectile vomiting, head injury signs, non-blanching rash, or swallowing a non-food item is emergency.
- A parent expressing they might harm themselves or the baby, or that they cannot cope, is crisis.
- Garbled or partial text (voice transcription) that hints at a red flag: escalate anyway. When unsure between two levels, pick the more severe one.
- Ordinary soothing/feeding/sleep questions are none."""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass(frozen=True)
class ClassifierResult:
    level: TriageLevel
    reasons: tuple[str, ...]
    raw: dict[str, Any]


class SafetyClassifier:
    """Injectable-client wrapper so tests never touch the network."""

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        timeout_s: float = CLASSIFIER_TIMEOUT_S,
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

    async def classify(self, content: str, age_days: int | None) -> ClassifierResult | None:
        try:
            return await asyncio.wait_for(self._classify(content, age_days), self._timeout_s)
        except Exception:
            logger.warning("safety classifier degraded (returning None)", exc_info=True)
            return None

    async def _classify(self, content: str, age_days: int | None) -> ClassifierResult | None:
        age_note = f"{age_days} days" if age_days is not None else "unknown (treat as under 3 months)"
        response = await self._get_client().messages.create(
            model=self._get_model(),
            max_tokens=200,
            system=CLASSIFIER_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"Child age: {age_note}\nParent message: {content}",
                }
            ],
        )
        raw_text = response.content[0].text
        data = json.loads(_FENCE_RE.sub("", raw_text).strip())
        level = TriageLevel(data["triage"])  # ValueError on unknown → degraded
        reasons = tuple(str(r) for r in data.get("reasons", []))
        return ClassifierResult(level=level, reasons=reasons, raw=data)
