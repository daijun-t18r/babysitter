"""Triage levels, the leading-tag stream parser, and the dosing-leak output filter.

Fail direction everywhere: over-escalate. A malformed or missing tag is itself
a signal (treated as `none` + flagged + stricter output filter), never ignored.
"""

import logging
import re
from enum import Enum

logger = logging.getLogger(__name__)

TAG_BUFFER_CAP = 120

TRIAGE_TAG_RE = re.compile(r'^\s*<triage\s+level="(\w+)"\s+reason="([\w-]+)"\s*/>')


class TriageLevel(str, Enum):
    NONE = "none"
    SEE_DOCTOR = "see_doctor"
    URGENT = "urgent"
    EMERGENCY = "emergency"
    CRISIS = "crisis"

    @property
    def severity(self) -> int:
        return _SEVERITY[self]


_SEVERITY = {
    TriageLevel.NONE: 0,
    TriageLevel.SEE_DOCTOR: 1,
    TriageLevel.URGENT: 2,
    TriageLevel.EMERGENCY: 3,
    TriageLevel.CRISIS: 4,
}


def parse_level(value: str) -> TriageLevel | None:
    try:
        return TriageLevel(value)
    except ValueError:
        return None


def merge_levels(*levels: TriageLevel | None) -> TriageLevel:
    """max severity across signal sources (rules / classifier / model tag)."""
    present = [level for level in levels if level is not None]
    if not present:
        return TriageLevel.NONE
    return max(present, key=lambda level: level.severity)


class TriageTagParser:
    """Streaming parser for the mandatory leading triage tag.

    Buffers incoming chunks until the first '/>' (capped at TAG_BUFFER_CAP
    chars), strips a well-formed tag, and passes everything else through.
    Malformed or missing tags set `malformed=True`; broken tag-like prefixes
    are stripped rather than leaked to the client/TTS.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self.done = False
        self.malformed = False
        self.level: TriageLevel | None = None
        self.reason: str | None = None

    def feed(self, chunk: str) -> str:
        if self.done:
            return chunk
        self._buffer += chunk
        stripped = self._buffer.lstrip()
        if not stripped:
            return ""

        # Fast malformed exit: cannot possibly be the start of a triage tag.
        probe = stripped[: len("<triage")]
        if not "<triage".startswith(probe):
            return self._finish_malformed(emit=self._buffer)

        end = self._buffer.find("/>")
        if end != -1:
            match = TRIAGE_TAG_RE.match(self._buffer)
            if match:
                level = parse_level(match.group(1))
                if level is not None:
                    self.level = level
                    self.reason = match.group(2)
                    self.done = True
                    return self._buffer[match.end() :].lstrip("\n")
            # Tag-shaped but broken: strip through '/>' so it never reaches TTS.
            return self._finish_malformed(emit=self._buffer[end + 2 :].lstrip("\n"))

        if len(self._buffer) > TAG_BUFFER_CAP:
            return self._finish_malformed(emit=self._buffer)
        return ""

    def finalize(self) -> str:
        """Call when the stream ends. Returns any remaining buffered text."""
        if self.done:
            return ""
        remaining = self._buffer
        stripped = remaining.lstrip()
        # A dangling partial tag carries no user-visible content; drop it.
        if stripped.startswith("<triage") or "<triage".startswith(stripped[: len("<triage")]):
            remaining = ""
        return self._finish_malformed(emit=remaining)

    def _finish_malformed(self, emit: str) -> str:
        self.done = True
        self.malformed = True
        self.level = None
        self.reason = None
        self._buffer = ""
        logger.warning("triage tag malformed or missing in model output")
        return emit


# --- Dosing-leak output filter -------------------------------------------------

SAFE_DOSING_MESSAGE = (
    "I can't give medication doses — the right amount depends on your baby's exact "
    "weight and the specific product's concentration, and getting it wrong is dangerous. "
    "Check the label with your pediatrician's office or a 24-hour nurse line; they can "
    "confirm the right dose even at this hour. If your baby may have already gotten too "
    "much of anything, call Poison Control now: 1-800-222-1222."
)

_MEDICATION_NAMES = (
    r"tylenol|acetaminophen|paracetamol|motrin|advil|ibuprofen|benadryl|"
    r"diphenhydramine|zyrtec|cetirizine|claritin|loratadine|simethicone|"
    r"gas\s*drops|gripe\s*water|vitamin\s*d|aspirin|amoxicillin|antibiotic"
)
_MED_RE = re.compile(_MEDICATION_NAMES, re.IGNORECASE)

_DOSE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mg|milligrams?|ml|mls|milliliters?|millilitres?|cc|ccs|"
    r"mcg|micrograms?|tsp|teaspoons?|dropper(?:s|ful|fuls)?|syringes?)\b",
    re.IGNORECASE,
)

_DOSE_PROXIMITY_CHARS = 80


def scan_dosing_leak(text: str, strict: bool = False) -> bool:
    """True if text states a numeric dose near a medication name.

    Strict mode (used when the triage tag was malformed) flags any numeric
    dose-unit expression, medication name or not. Category facts without
    numbers-with-units ("no ibuprofen under 6 months") never trigger.
    """
    for match in _DOSE_RE.finditer(text):
        if strict:
            return True
        window_start = max(0, match.start() - _DOSE_PROXIMITY_CHARS)
        window = text[window_start : match.end() + _DOSE_PROXIMITY_CHARS]
        if _MED_RE.search(window):
            return True
    return False


class DosingLeakFilter:
    """Streaming wrapper that never lets a dose reach the client.

    Holds back a small tail so a dose split across chunks is caught before any
    part of it is emitted. On trigger, the caller replaces the message with
    SAFE_DOSING_MESSAGE (exposed here as `final_text`).
    """

    HOLDBACK_CHARS = 64

    def __init__(self, strict: bool = False) -> None:
        self.strict = strict
        self.triggered = False
        self._accumulated = ""
        self._emitted = 0

    def escalate(self) -> None:
        """Switch to strict scanning (malformed triage tag)."""
        self.strict = True

    def feed(self, chunk: str) -> str:
        if self.triggered:
            return ""
        self._accumulated += chunk
        if scan_dosing_leak(self._accumulated, strict=self.strict):
            self.triggered = True
            logger.error("dosing leak blocked in model output")
            return ""
        releasable = len(self._accumulated) - self.HOLDBACK_CHARS
        if releasable > self._emitted:
            out = self._accumulated[self._emitted : releasable]
            self._emitted = releasable
            return out
        return ""

    def finalize(self) -> str:
        if self.triggered:
            return ""
        out = self._accumulated[self._emitted :]
        self._emitted = len(self._accumulated)
        return out

    @property
    def final_text(self) -> str:
        """The text to persist for this assistant message."""
        return SAFE_DOSING_MESSAGE if self.triggered else self._accumulated
