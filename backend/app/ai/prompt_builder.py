"""System prompt compilation.

Static blocks (persona + safety + knowledge packs) are compiled once and carry
a prompt-cache breakpoint (cache_control ephemeral on the last static block).
The dynamic <child_context> block always comes AFTER the breakpoint so the
cache hits across turns and users.

Age math lives here in one tested function. Within one week of an age-band
boundary the YOUNGER band's cautions apply (conservative direction).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

PROMPTS_DIR = Path(__file__).parent / "prompts"

AGE_BANDS = ("0-3m", "3-6m", "6-12m", "12m+")
_BAND_LOWER_DAYS = {"3-6m": 91, "6-12m": 182, "12m+": 365}
BOUNDARY_GRACE_DAYS = 7

PROTOCOL_REMINDER = """# Final reminder — triage tag protocol

Your reply MUST begin with exactly one tag before any other character:
<triage level="none|see_doctor|urgent|emergency|crisis" reason="<slug>"/>
Then answer following your format rules. The tag never appears in the visible text and you never mention it."""


@dataclass(frozen=True)
class ChildAge:
    days: int
    weeks: int
    rem_days: int
    band: str
    raw_band: str
    conservative_applied: bool
    corrected_days: int | None
    corrected_weeks: int | None


def _band_for(days: int) -> str:
    if days < _BAND_LOWER_DAYS["3-6m"]:
        return "0-3m"
    if days < _BAND_LOWER_DAYS["6-12m"]:
        return "3-6m"
    if days < _BAND_LOWER_DAYS["12m+"]:
        return "6-12m"
    return "12m+"


def utc_today() -> date:
    return datetime.now(UTC).date()


def compute_child_age(
    birth_date: date, due_date: date | None = None, today: date | None = None
) -> ChildAge:
    """The one age-math function. Chronological always; corrected when preterm."""
    today = today or utc_today()
    days = max((today - birth_date).days, 0)
    weeks, rem_days = divmod(days, 7)

    raw_band = _band_for(days)
    band = raw_band
    conservative = False
    lower = _BAND_LOWER_DAYS.get(raw_band)
    if lower is not None and days < lower + BOUNDARY_GRACE_DAYS:
        band = AGE_BANDS[AGE_BANDS.index(raw_band) - 1]
        conservative = True

    corrected_days: int | None = None
    corrected_weeks: int | None = None
    if due_date is not None and due_date > birth_date:
        corrected_days = max(days - (due_date - birth_date).days, 0)
        corrected_weeks = corrected_days // 7

    return ChildAge(
        days=days,
        weeks=weeks,
        rem_days=rem_days,
        band=band,
        raw_band=raw_band,
        conservative_applied=conservative,
        corrected_days=corrected_days,
        corrected_weeks=corrected_weeks,
    )


@lru_cache
def load_static_blocks() -> tuple[str, ...]:
    base = (PROMPTS_DIR / "system_base.md").read_text(encoding="utf-8")
    safety = (PROMPTS_DIR / "safety_core.md").read_text(encoding="utf-8")
    knowledge_files = sorted((PROMPTS_DIR / "knowledge").glob("*.md"))
    knowledge = "\n\n".join(p.read_text(encoding="utf-8") for p in knowledge_files)
    return (base, safety, knowledge + "\n\n" + PROTOCOL_REMINDER)


def build_system_blocks(child_context: str) -> list[dict[str, Any]]:
    static = load_static_blocks()
    blocks: list[dict[str, Any]] = []
    for i, text in enumerate(static):
        block: dict[str, Any] = {"type": "text", "text": text}
        if i == len(static) - 1:
            block["cache_control"] = {"type": "ephemeral"}  # cache breakpoint
        blocks.append(block)
    # Dynamic content strictly after the breakpoint.
    blocks.append({"type": "text", "text": child_context})
    return blocks


class _EventLike(Protocol):
    occurred_at: datetime
    summary: str
    kind: str


def format_recent_events(events: list[_EventLike], now: datetime | None = None) -> list[str]:
    """Human phrasing for confirmed events, newest first: "2 hours ago: breastfed"."""
    now = now or datetime.now(UTC)
    lines: list[str] = []
    for event in events:
        minutes = max(int((now - event.occurred_at).total_seconds() // 60), 0)
        if minutes < 60:
            ago = f"{minutes} min ago"
        elif minutes < 60 * 24:
            hours, rem = divmod(minutes, 60)
            ago = f"{hours}h {rem}m ago" if rem else f"{hours} hours ago"
        else:
            ago = f"{minutes // (60 * 24)} days ago"
        lines.append(f"{ago}: {event.summary} ({event.kind})")
    return lines


def _coarse_time_of_day(hour: int) -> str:
    if hour < 5:
        return "the middle of the night"
    if hour < 8:
        return "early morning"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 21:
        return "evening"
    return "late night"


def build_child_context(
    *,
    name: str,
    birth_date: date,
    due_date: date | None = None,
    feeding_type: str | None = None,
    notes: str | None = None,
    today: date | None = None,
    local_hour: int | None = None,
    recent_events: list[str] | None = None,
) -> str:
    age = compute_child_age(birth_date, due_date, today)
    lines = ["<child_context>", f"Baby: {name}"]
    lines.append(
        f"Age: {age.weeks} weeks, {age.rem_days} days old ({age.days} days, chronological)"
    )
    if age.corrected_days is not None:
        early_weeks = ((due_date - birth_date).days + 6) // 7  # type: ignore[operator]
        lines.append(
            f"Corrected age: {age.corrected_weeks} weeks ({age.corrected_days} days; born about "
            f"{early_weeks} weeks early). Use corrected age for development and sleep "
            "expectations. Use CHRONOLOGICAL age for the under-3-month fever rule."
        )
    band_note = ""
    if age.conservative_applied:
        band_note = (
            f" (within one week past the {age.raw_band} boundary — apply the younger "
            f"band's cautions)"
        )
    lines.append(f"Age band: {age.band}{band_note}")
    if feeding_type:
        lines.append(f"Feeding: {feeding_type}")
    if local_hour is not None:
        lines.append(f"Local time for the parent: {_coarse_time_of_day(local_hour)}")
    if recent_events:
        # Only parent-confirmed events ever reach this list (query-layer invariant).
        lines.append("Recent confirmed events (newest first):")
        lines.extend(f"- {line}" for line in recent_events)
    if notes:
        lines.append(f"Parent notes (unverified, the parent's own words): {notes}")
    lines.append("</child_context>")
    return "\n".join(lines)
