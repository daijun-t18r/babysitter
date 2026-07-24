"""Passive-memory event endpoints (Phase 3).

Confirmation is the gate: only parent-confirmed events are ever injected into
prompts, and only unconfirmed events can be dismissed (deleted).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_repo
from app.api.serializers import serialize_event
from app.core.auth import CurrentUser
from app.db.repo import Repo

router = APIRouter()


class ConfirmBatchRequest(BaseModel):
    event_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


@router.get("/events")
async def list_confirmed_events(
    user: CurrentUser,
    repo: Annotated[Repo, Depends(get_repo)],
    child_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict[str, Any]:
    events = await repo.list_confirmed_events(user.user_id, child_id, limit=limit)
    return {"events": [serialize_event(e) for e in events]}


@router.get("/events/pending")
async def list_pending_events(
    user: CurrentUser,
    repo: Annotated[Repo, Depends(get_repo)],
    child_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    events = await repo.list_pending_events(user.user_id, child_id, limit=limit)
    return {"events": [serialize_event(e) for e in events]}


@router.post("/events/{event_id}/confirm")
async def confirm_event(
    event_id: uuid.UUID,
    user: CurrentUser,
    repo: Annotated[Repo, Depends(get_repo)],
) -> dict[str, Any]:
    event = await repo.get_event(event_id, user.user_id)
    if event is None:
        raise HTTPException(404, detail="Event not found")
    await repo.confirm_events([event_id], user.user_id)
    return {"event": serialize_event(event)}


@router.post("/events/confirm-batch")
async def confirm_batch(
    body: ConfirmBatchRequest,
    user: CurrentUser,
    repo: Annotated[Repo, Depends(get_repo)],
) -> dict[str, Any]:
    confirmed = await repo.confirm_events(list(body.event_ids), user.user_id)
    return {"confirmed": confirmed}


@router.delete("/events/{event_id}", status_code=204)
async def dismiss_event(
    event_id: uuid.UUID,
    user: CurrentUser,
    repo: Annotated[Repo, Depends(get_repo)],
) -> None:
    event = await repo.get_event(event_id, user.user_id)
    if event is None:
        raise HTTPException(404, detail="Event not found")
    if event.confirmed:
        raise HTTPException(400, detail="Confirmed events cannot be dismissed")
    await repo.delete_event(event_id, user.user_id)
