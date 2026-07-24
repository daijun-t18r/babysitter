"""GET /api/v1/morning-summary — the passive morning-after card (Phase 3).

Passive by design: no push notifications; the card only exists when the
parent opens the app. Night window is 20:00–06:00 local; before 06:00 the
night is still ongoing and the answer is null. Failures degrade to null —
a missing card is always acceptable, a wrong one is not.

Cache is in-process per (user, night): one model call per user per morning,
reset on deploy. Fine at MVP scale; revisit if the API becomes multi-replica.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.ai.prompt_builder import compute_child_age
from app.api.deps import RepoFactory, get_repo_factory
from app.core.auth import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter()

NIGHT_START_HOUR = 20
NIGHT_END_HOUR = 6
MAX_CACHE_ENTRIES = 2000
TRANSCRIPT_MESSAGE_CAP = 40


def night_window_utc(
    now_utc: datetime, tz_offset_minutes: int
) -> tuple[datetime, datetime, str] | None:
    """(start_utc, end_utc, night_date_iso) for the most recent completed night,
    or None while the night is still ongoing (local hour < 6)."""
    offset = timedelta(minutes=tz_offset_minutes)
    local_now = now_utc + offset
    if local_now.hour < NIGHT_END_HOUR:
        return None
    end_local = local_now.replace(hour=NIGHT_END_HOUR, minute=0, second=0, microsecond=0)
    start_local = end_local - timedelta(hours=24 - NIGHT_START_HOUR + NIGHT_END_HOUR)
    return (start_local - offset, end_local - offset, local_now.date().isoformat())


@router.get("/morning-summary")
async def morning_summary(
    request: Request,
    user: CurrentUser,
    repo_factory: Annotated[RepoFactory, Depends(get_repo_factory)],
    tz_offset_minutes: Annotated[int, Query(ge=-840, le=840)] = 0,
) -> dict[str, Any]:
    window = night_window_utc(datetime.now(UTC), tz_offset_minutes)
    if window is None:
        return {"summary": None}
    start_utc, end_utc, night_date = window

    cache: dict[tuple[str, str], str] = request.app.state.morning_cache
    cache_key = (user.user_id, night_date)
    if cache_key in cache:
        return {"summary": cache[cache_key], "night_date": night_date}

    async with repo_factory() as repo:
        messages = await repo.list_user_messages_between(user.user_id, start_utc, end_utc)
        night_messages = [m for m in messages if m.role in ("user", "assistant")]
        if not any(m.role == "user" for m in night_messages):
            return {"summary": None}

        events = await repo.list_confirmed_events_between(user.user_id, start_utc, end_utc)
        children = await repo.list_children(user.user_id)

    child_note = "The baby's age is unknown."
    if children:
        child = children[0]
        age = compute_child_age(child.birth_date, child.due_date)
        child_note = f"The baby ({child.name}) is {age.weeks} weeks old (age band {age.band})."

    lines = [
        f"{m.role}: {m.content}" for m in night_messages[-TRANSCRIPT_MESSAGE_CAP:]
    ]
    if events:
        lines.append("Confirmed events that night:")
        lines.extend(f"- {e.summary} ({e.kind})" for e in events)

    summarizer = request.app.state.morning_summarizer
    text = await summarizer.summarize("\n".join(lines), child_note)
    if text is None:
        return {"summary": None}

    if len(cache) >= MAX_CACHE_ENTRIES:
        cache.clear()
    cache[cache_key] = text
    return {"summary": text, "night_date": night_date}
