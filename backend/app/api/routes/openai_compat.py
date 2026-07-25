"""POST /v1/chat/completions — OpenAI-compatible endpoint for Vapi (Phase 2).

One brain, two transports: this endpoint reuses chat.py's ChatTurn +
chat_turn_events pipeline (rules engine on the latest user message, child
context + confirmed events in the prompt, Claude stream, triage-tag strip,
dosing-leak filter, safety_events audit writes, message persistence with
input_mode='voice') and adapts the (event, data) tuples into OpenAI
chat.completion.chunk SSE frames. Safety events never appear in the OpenAI
stream — the PWA receives triage cards via Supabase Realtime on the
safety_events table (migration 002); escalation copy embedded in the spoken
text is the double insurance.

Auth is two-layer and fails closed (both required, 401 otherwise):
1. X-Vapi-Secret header — the static shared secret, constant-time compare.
2. Voice session token — short-lived HMAC token minted by
   POST /api/v1/voice/session, passed through Vapi assistant metadata and
   read from body.metadata.session_token (fallback:
   body.call.assistantOverrides.metadata.session_token — see CONTRACTS.md).

Dev fallback: with VAPI_SHARED_SECRET unset and ENV=dev the endpoint serves
an anonymous generic-child-context reply (no identity, no persistence, no
audit) so local spikes work without secrets. Outside dev, unset secret → 503.
"""

import hmac
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.ai.chat_service import ChatService
from app.ai.prompt_builder import (
    build_child_context,
    build_system_blocks,
    compute_child_age,
    format_recent_events,
)
from app.ai.triage import SAFE_DOSING_MESSAGE, DosingLeakFilter, TriageTagParser
from app.api.deps import (
    SafetyRecorder,
    UserRepoFactory,
    get_safety_recorder,
    get_user_repo_factory,
)
from app.api.routes.chat import (
    HISTORY_LIMIT,
    RECENT_EVENTS_LIMIT,
    RECENT_EVENTS_WINDOW_H,
    ChatTurn,
    chat_turn_events,
)
from app.core.config import get_settings
from app.core.voice_token import VoiceTokenError, verify_voice_token
from app.services.safety.rules import evaluate_rules

logger = logging.getLogger(__name__)

router = APIRouter()

VAPI_SECRET_HEADER = "x-vapi-secret"

# Per-process map of Vapi call id → conversation id so every turn of one call
# lands in the same conversation (best-effort: a restart or second instance
# just starts a fresh conversation, nothing breaks).
CALL_CONVERSATION_CAP = 512

_GENERIC_CHILD_CONTEXT = """<child_context>
No child profile is linked to this call yet. Assume an infant 0-12 months old.
Treat age as UNKNOWN: apply the most cautious (youngest) age band's rules,
including the under-3-month fever rule.
</child_context>"""


def _check_secret(request: Request) -> bool:
    """True → secret configured and matched; False → anonymous dev mode.

    Raises 401 on mismatch (constant-time compare) and 503 when the endpoint
    is not configured outside dev.
    """
    settings = get_settings()
    if not settings.vapi_shared_secret:
        if settings.is_dev:
            return False
        raise HTTPException(503, detail="Voice endpoint not configured")
    provided = request.headers.get(VAPI_SECRET_HEADER) or ""
    if not hmac.compare_digest(provided.encode(), settings.vapi_shared_secret.encode()):
        raise HTTPException(401, detail="Invalid shared secret")
    return True


def _extract_session_token(body: dict[str, Any]) -> str | None:
    """Documented location first (body.metadata), then the shape Vapi echoes
    assistant overrides into (body.call.assistantOverrides.metadata)."""
    metadata = body.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("session_token"), str):
        return metadata["session_token"]
    call = body.get("call")
    if isinstance(call, dict):
        overrides = call.get("assistantOverrides")
        if isinstance(overrides, dict):
            metadata = overrides.get("metadata")
            if isinstance(metadata, dict) and isinstance(metadata.get("session_token"), str):
                return metadata["session_token"]
    return None


def _chunk_frame(
    completion_id: str,
    created: int,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None,
) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    recorder: Annotated[SafetyRecorder, Depends(get_safety_recorder)],
    repo_factory_for: Annotated[UserRepoFactory, Depends(get_user_repo_factory)],
) -> Any:
    authenticated = _check_secret(request)
    body = await request.json()
    stream = bool(body.get("stream", True))
    messages_in = body.get("messages") or []

    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in messages_in
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
    ]
    last_user = next((m for m in reversed(messages) if m["role"] == "user"), None)
    if last_user is None:
        raise HTTPException(400, detail="No user message provided")
    user_content: str = last_user["content"]

    chat_service: ChatService = request.app.state.chat_service
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model_name = body.get("model") or chat_service.model

    if not authenticated:
        text_source = _anonymous_dev_text(chat_service, user_content, messages)
    else:
        token = _extract_session_token(body)
        if not token:
            raise HTTPException(401, detail="Missing session token")
        try:
            session = verify_voice_token(token, get_settings().vapi_shared_secret)
        except VoiceTokenError:
            raise HTTPException(401, detail="Invalid session token") from None

        turn = await _build_voice_turn(
            request=request,
            user_id=session.user_id,
            child_id=session.child_id,
            call_id=_call_id(body),
            user_content=user_content,
            messages=messages,
            recorder=recorder,
            repo_factory_for=repo_factory_for,
        )
        text_source = _pipeline_text(turn)

    if stream:

        async def sse() -> AsyncIterator[str]:
            yield _chunk_frame(completion_id, created, model_name, {"role": "assistant"}, None)
            async for text in text_source:
                yield _chunk_frame(completion_id, created, model_name, {"content": text}, None)
            yield _chunk_frame(completion_id, created, model_name, {}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    full_text = "".join([text async for text in text_source])
    return JSONResponse(
        {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": full_text},
                    "finish_reason": "stop",
                }
            ],
        }
    )


def _call_id(body: dict[str, Any]) -> str | None:
    call = body.get("call")
    if isinstance(call, dict) and isinstance(call.get("id"), str):
        return call["id"]
    return None


async def _build_voice_turn(
    *,
    request: Request,
    user_id: str,
    child_id: str,
    call_id: str | None,
    user_content: str,
    messages: list[dict[str, Any]],
    recorder: SafetyRecorder,
    repo_factory_for: UserRepoFactory,
) -> ChatTurn:
    """Mirror of chat.py's pre-stream setup, with identity from the token and
    history from Vapi's request body instead of the database."""
    repo_factory = repo_factory_for(user_id)
    call_map: dict[str, uuid.UUID] = request.app.state.voice_call_conversations

    async with repo_factory() as repo:
        child = await repo.get_child(child_id, user_id)
        if child is None:
            raise HTTPException(404, detail="Child not found")

        conversation = None
        if call_id and call_id in call_map:
            conversation = await repo.get_conversation(call_map[call_id], user_id)
        if conversation is None:
            conversation = await repo.create_conversation(
                user_id, child.id, title=user_content[:80]
            )
            if call_id:
                call_map[call_id] = conversation.id
                while len(call_map) > CALL_CONVERSATION_CAP:
                    call_map.pop(next(iter(call_map)))

        user_message = await repo.add_message(
            conversation_id=conversation.id,
            role="user",
            content=user_content,
            input_mode="voice",
        )
        recent_confirmed = await repo.list_confirmed_events_since(
            child.id,
            user_id,
            since=datetime.now(UTC) - timedelta(hours=RECENT_EVENTS_WINDOW_H),
            limit=RECENT_EVENTS_LIMIT,
        )
        conversation_id = conversation.id
        user_message_id = user_message.id
        child_uuid = child.id
        child_name = child.name
        child_birth_date = child.birth_date
        child_due_date = child.due_date
        child_feeding_type = child.feeding_type
        child_notes = child.notes
    # Session committed here: the user turn is durable before streaming.

    age = compute_child_age(child_birth_date, child_due_date)
    rules_result = evaluate_rules(user_content, age.days)

    child_context = build_child_context(
        name=child_name,
        birth_date=child_birth_date,
        due_date=child_due_date,
        feeding_type=child_feeding_type,
        notes=child_notes,
        local_hour=datetime.now(UTC).hour,
        recent_events=format_recent_events(recent_confirmed),
    )

    return ChatTurn(
        user_id=user_id,
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        child_age_days=age.days,
        input_mode="voice",
        rules_result=rules_result,
        system_blocks=build_system_blocks(child_context),
        messages=messages[-(HISTORY_LIMIT + 1) :],
        chat_service=request.app.state.chat_service,
        classifier=request.app.state.classifier,
        repo_factory=repo_factory,
        recorder=recorder,
        user_content=user_content,
        child_id=child_uuid,
        extractor=getattr(request.app.state, "memory_extractor", None),
    )


async def _pipeline_text(turn: ChatTurn) -> AsyncIterator[str]:
    """Adapter: chat_turn_events (event, data) tuples → plain text pieces.

    `delta` carries visible text; `error` carries the friendly fallback copy
    (spoken by TTS instead of dead air). `start`/`safety`/`done` are
    side-channel only — safety cards travel via safety_events → Realtime.
    """
    async for event, data in chat_turn_events(turn):
        if event == "delta":
            yield data["text"]
        elif event == "error":
            yield data["message"]


async def _anonymous_dev_text(
    chat_service: ChatService, user_content: str, messages: list[dict[str, Any]]
) -> AsyncIterator[str]:
    """Dev-only path (no secret configured): generic context, tag strip and
    dosing filter still apply, nothing is persisted or audited."""
    rules_result = evaluate_rules(user_content, age_days=None)
    if rules_result.fired:
        logger.warning(
            "voice dev-mode rules hit (unpersisted): %s", list(rules_result.matched)
        )

    tag_parser = TriageTagParser()
    dosing = DosingLeakFilter()
    system_blocks = build_system_blocks(_GENERIC_CHILD_CONTEXT)
    async for chunk in chat_service.stream_text(system=system_blocks, messages=messages):
        visible = tag_parser.feed(chunk)
        if tag_parser.done and tag_parser.malformed:
            dosing.escalate()
        if visible:
            safe = dosing.feed(visible)
            if dosing.triggered:
                yield SAFE_DOSING_MESSAGE
                return
            if safe:
                yield safe
    tail = tag_parser.finalize()
    if tag_parser.malformed:
        dosing.escalate()
    out = dosing.feed(tail) if tail else ""
    if dosing.triggered:
        yield SAFE_DOSING_MESSAGE
        return
    out += dosing.finalize()
    if out:
        yield out
