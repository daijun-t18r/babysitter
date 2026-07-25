"""POST /v1/chat/completions — OpenAI-compatible streaming for Vapi (Phase 2).

Same brain internally: rules engine on the last user message, the same system
prompt, leading triage tag stripped, dosing-leak filter applied. The triage
side-channel (safety_events insert → Supabase Realtime) and per-user child
context require caller-identity mapping and land with Phase 2.

TODO(Phase 2):
- Vapi-specific auth: replace the plain shared-secret header check below with
  the production secret provisioning story (per-assistant secrets, rotation).
- Map Vapi call metadata / caller id → user + child, then inject real
  <child_context> and persist messages + safety_events (service_session).
"""

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.ai.chat_service import ChatService
from app.ai.prompt_builder import build_system_blocks
from app.ai.triage import SAFE_DOSING_MESSAGE, DosingLeakFilter, TriageTagParser
from app.core.config import get_settings
from app.services.safety.rules import evaluate_rules

router = APIRouter()

VAPI_SECRET_HEADER = "x-vapi-secret"

_GENERIC_CHILD_CONTEXT = """<child_context>
No child profile is linked to this call yet. Assume an infant 0-12 months old.
Treat age as UNKNOWN: apply the most cautious (youngest) age band's rules,
including the under-3-month fever rule.
</child_context>"""


def _check_auth(request: Request) -> None:
    settings = get_settings()
    secret = request.headers.get(VAPI_SECRET_HEADER)
    if settings.vapi_shared_secret:
        if secret != settings.vapi_shared_secret:
            raise HTTPException(401, detail="Invalid shared secret")
    elif not settings.is_dev:
        raise HTTPException(503, detail="Voice endpoint not configured")


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    _check_auth(request)
    body = await request.json()
    messages_in = body.get("messages") or []
    stream = bool(body.get("stream", True))

    last_user = next(
        (m for m in reversed(messages_in) if m.get("role") == "user" and m.get("content")),
        None,
    )
    user_content = last_user["content"] if last_user else ""

    # Deterministic rules still run on voice transcripts; with no identity
    # mapping yet the result reaches the caller through the model's escalation
    # copy (numbers embedded in text), not through Realtime cards.
    rules_result = evaluate_rules(user_content, age_days=None)

    chat_service: ChatService = request.app.state.chat_service
    system_blocks = build_system_blocks(_GENERIC_CHILD_CONTEXT)
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in messages_in
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    if not messages:
        raise HTTPException(400, detail="No user message provided")

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model_name = body.get("model") or chat_service.model

    async def generate_text() -> AsyncIterator[str]:
        tag_parser = TriageTagParser()
        # Strict filter when the tag is malformed, same as the SSE path.
        dosing = DosingLeakFilter()
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
        _ = rules_result  # TODO(Phase 2): persist safety_events once identity is mapped

    def _chunk_payload(delta: dict[str, Any], finish_reason: str | None) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(payload)}\n\n"

    if stream:

        async def sse() -> AsyncIterator[str]:
            yield _chunk_payload({"role": "assistant"}, None)
            async for text in generate_text():
                yield _chunk_payload({"content": text}, None)
            yield _chunk_payload({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    full_text = "".join([text async for text in generate_text()])
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
