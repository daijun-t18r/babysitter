import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_repo
from app.api.serializers import serialize_conversation, serialize_message
from app.core.auth import CurrentUser
from app.db.repo import Repo

router = APIRouter()


@router.get("/conversations")
async def list_conversations(
    user: CurrentUser,
    repo: Annotated[Repo, Depends(get_repo)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    conversations = await repo.list_conversations(user.user_id, limit=limit)
    return {"conversations": [serialize_conversation(c) for c in conversations]}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    user: CurrentUser,
    repo: Annotated[Repo, Depends(get_repo)],
) -> dict[str, Any]:
    conversation = await repo.get_conversation(conversation_id, user.user_id)
    if conversation is None:
        raise HTTPException(404, detail="Conversation not found")
    messages = await repo.list_messages(conversation_id)
    payload = serialize_conversation(conversation)
    payload["messages"] = [serialize_message(m) for m in messages]
    return payload
