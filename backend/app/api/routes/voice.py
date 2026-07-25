"""POST /api/v1/voice/session — mint the short-lived voice session token.

The logged-in PWA calls this right before starting a Vapi call. The token
binds {user_id, child_id, exp ≤ 15 min}; the frontend places it in Vapi
assistantOverrides.metadata.session_token, Vapi echoes it into every
custom-llm request, and /v1/chat/completions verifies it to load the child
context. Authed like every other /api/v1 route (Supabase JWT).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_repo
from app.core.auth import CurrentUser
from app.core.config import get_settings
from app.core.voice_token import mint_voice_token
from app.db.repo import Repo

router = APIRouter()


class VoiceSessionRequest(BaseModel):
    child_id: uuid.UUID


@router.post("/voice/session")
async def create_voice_session(
    body: VoiceSessionRequest,
    user: CurrentUser,
    repo: Annotated[Repo, Depends(get_repo)],
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.vapi_shared_secret:
        raise HTTPException(503, detail="Voice is not configured")

    child = await repo.get_child(body.child_id, user.user_id)
    if child is None:
        raise HTTPException(404, detail="Child not found")

    token, expires_at = mint_voice_token(
        user_id=user.user_id,
        child_id=str(body.child_id),
        secret=settings.vapi_shared_secret,
    )
    return {"token": token, "expires_at": expires_at.isoformat()}
