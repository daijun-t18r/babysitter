"""POST /api/v1/chat — the SSE safety pipeline.

Event order per CONTRACTS.md: start → safety (may repeat; client takes max) →
delta (triage tag already stripped) → done. `error` on failure.

Flow: auth → load child under RLS → persist the user message (committed before
streaming so it survives disconnects) → run the deterministic rules engine
synchronously, emitting + auditing immediately on a hit → launch the main
Claude stream and the Haiku classifier concurrently → strip the leading triage
tag → run the dosing-leak output filter → merge severities (always max) →
persist the assistant message even if the client disconnected → sticky-update
the conversation's max_triage.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.ai.chat_service import ChatService
from app.ai.prompt_builder import (
    build_child_context,
    build_system_blocks,
    compute_child_age,
    format_recent_events,
)
from app.ai.triage import (
    SAFE_DOSING_MESSAGE,
    DosingLeakFilter,
    TriageLevel,
    TriageTagParser,
    merge_levels,
)
from app.api.deps import RepoFactory, SafetyRecorder, get_repo_factory, get_safety_recorder
from app.core.auth import CurrentUser
from app.services.safety.rules import RuleResult, evaluate_rules

logger = logging.getLogger(__name__)

router = APIRouter()

HISTORY_LIMIT = 20
RECENT_EVENTS_WINDOW_H = 24
RECENT_EVENTS_LIMIT = 10

# Fire-and-forget extraction tasks: keep strong references so the event loop
# never garbage-collects one mid-flight.
_background_tasks: set[asyncio.Task[Any]] = set()


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    child_id: uuid.UUID
    content: str = Field(min_length=1, max_length=8000)
    input_mode: Literal["text", "voice"] = "text"


@dataclass
class ChatTurn:
    """Everything the stream generator needs, resolved before streaming starts."""

    user_id: str
    conversation_id: uuid.UUID
    user_message_id: uuid.UUID
    child_age_days: int
    input_mode: str
    rules_result: RuleResult
    system_blocks: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    chat_service: ChatService
    classifier: Any
    repo_factory: RepoFactory
    recorder: SafetyRecorder
    user_content: str
    child_id: uuid.UUID | None = None
    extractor: Any = None  # MemoryExtractor-shaped; None disables extraction
    extraction_task: asyncio.Task[Any] | None = None
    model: str = ""

    def __post_init__(self) -> None:
        if not self.model:
            self.model = self.chat_service.model


@dataclass
class _TurnState:
    model_level: TriageLevel | None = None
    model_reason: str | None = None
    malformed_tag: bool = False
    classifier_level: TriageLevel | None = None
    classifier_reason: str | None = None
    classifier_failed: bool = True
    persisted: bool = False
    assistant_message_id: uuid.UUID | None = None
    filter_triggered: bool = False
    extra_matched: list[str] = field(default_factory=list)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    user: CurrentUser,
    repo_factory: Annotated[RepoFactory, Depends(get_repo_factory)],
    recorder: Annotated[SafetyRecorder, Depends(get_safety_recorder)],
) -> StreamingResponse:
    chat_service: ChatService = request.app.state.chat_service
    classifier = request.app.state.classifier

    async with repo_factory() as repo:
        child = await repo.get_child(body.child_id, user.user_id)
        if child is None:
            raise HTTPException(404, detail="Child not found")

        if body.conversation_id is not None:
            conversation = await repo.get_conversation(body.conversation_id, user.user_id)
            if conversation is None:
                raise HTTPException(404, detail="Conversation not found")
        else:
            conversation = await repo.create_conversation(
                user.user_id, child.id, title=body.content[:80]
            )

        history = await repo.list_messages(conversation.id, limit=HISTORY_LIMIT)
        user_message = await repo.add_message(
            conversation_id=conversation.id,
            role="user",
            content=body.content,
            input_mode=body.input_mode,
        )
        recent_confirmed = await repo.list_confirmed_events_since(
            child.id,
            user.user_id,
            since=datetime.now(UTC) - timedelta(hours=RECENT_EVENTS_WINDOW_H),
            limit=RECENT_EVENTS_LIMIT,
        )
        conversation_id = conversation.id
        user_message_id = user_message.id
        child_name = child.name
        child_birth_date = child.birth_date
        child_due_date = child.due_date
        child_feeding_type = child.feeding_type
        child_notes = child.notes
    # Session committed here: the user message is durable before streaming.

    age = compute_child_age(child_birth_date, child_due_date)
    rules_result = evaluate_rules(body.content, age.days)

    child_context = build_child_context(
        name=child_name,
        birth_date=child_birth_date,
        due_date=child_due_date,
        feeding_type=child_feeding_type,
        notes=child_notes,
        # TODO: use the client's timezone once the frontend sends it (UTC for now).
        local_hour=datetime.now(UTC).hour,
        recent_events=format_recent_events(recent_confirmed),
    )
    system_blocks = build_system_blocks(child_context)
    messages = [
        {"role": m.role, "content": m.content} for m in history if m.role in ("user", "assistant")
    ]
    messages.append({"role": "user", "content": body.content})

    turn = ChatTurn(
        user_id=user.user_id,
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        child_age_days=age.days,
        input_mode=body.input_mode,
        rules_result=rules_result,
        system_blocks=system_blocks,
        messages=messages,
        chat_service=chat_service,
        classifier=classifier,
        repo_factory=repo_factory,
        recorder=recorder,
        user_content=body.content,
        child_id=body.child_id,
        extractor=getattr(request.app.state, "memory_extractor", None),
    )

    async def sse_stream() -> AsyncIterator[str]:
        async for event, data in chat_turn_events(turn):
            yield _sse(event, data)

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def chat_turn_events(turn: ChatTurn) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yields (event, data) tuples. Exposed separately so tests drive it directly."""
    state = _TurnState()
    tag_parser = TriageTagParser()
    dosing = DosingLeakFilter()
    rules = turn.rules_result

    classifier_task: asyncio.Task[Any] = asyncio.ensure_future(
        turn.classifier.classify(turn.user_content, turn.child_age_days)
    )

    try:
        yield (
            "start",
            {
                "conversation_id": str(turn.conversation_id),
                "user_message_id": str(turn.user_message_id),
            },
        )

        if rules.fired:
            yield (
                "safety",
                {"triage": rules.level.value, "reason": rules.reason, "source": "rules"},
            )
            await turn.recorder.record(
                user_id=turn.user_id,
                conversation_id=turn.conversation_id,
                message_id=turn.user_message_id,
                source="rules",
                triage_level=rules.level.value,
                matched_rules=list(rules.matched),
                child_age_days=turn.child_age_days,
            )

        tag_handled = False
        async for chunk in turn.chat_service.stream_text(
            system=turn.system_blocks, messages=turn.messages
        ):
            visible = tag_parser.feed(chunk)
            if tag_parser.done and not tag_handled:
                tag_handled = True
                async for event in _handle_tag(turn, state, tag_parser, dosing):
                    yield event
            if visible and not state.filter_triggered:
                safe = dosing.feed(visible)
                if dosing.triggered:
                    async for event in _handle_filter_trigger(turn, state):
                        yield event
                    break
                if safe:
                    yield ("delta", {"text": safe})

        if not state.filter_triggered:
            tail = tag_parser.finalize()
            if tag_parser.malformed and not tag_handled:
                tag_handled = True
                async for event in _handle_tag(turn, state, tag_parser, dosing):
                    yield event
            remaining = ""
            if tail:
                remaining += dosing.feed(tail)
            if not dosing.triggered:
                remaining += dosing.finalize()
                if remaining:
                    yield ("delta", {"text": remaining})
            else:
                async for event in _handle_filter_trigger(turn, state):
                    yield event

        # Classifier (has its own internal 2s timeout; failure → None).
        classifier_result = await classifier_task
        if classifier_result is not None:
            state.classifier_failed = False
            state.classifier_level = classifier_result.level
            state.classifier_reason = (
                classifier_result.reasons[0] if classifier_result.reasons else "general"
            )
            if classifier_result.level != TriageLevel.NONE:
                yield (
                    "safety",
                    {
                        "triage": classifier_result.level.value,
                        "reason": state.classifier_reason,
                        "source": "classifier",
                    },
                )
                await turn.recorder.record(
                    user_id=turn.user_id,
                    conversation_id=turn.conversation_id,
                    message_id=turn.user_message_id,
                    source="classifier",
                    triage_level=classifier_result.level.value,
                    classifier_output=classifier_result.raw,
                    child_age_days=turn.child_age_days,
                )

        final_level, final_reason = _merge_final(turn, state)
        degraded = (not rules.fired) and state.classifier_failed

        if _weak_hit_floor_applies(turn, state, final_level):
            final_level = TriageLevel.SEE_DOCTOR
            final_reason = final_reason or "general"
            yield (
                "safety",
                {"triage": final_level.value, "reason": "general", "source": "rules"},
            )
            await turn.recorder.record(
                user_id=turn.user_id,
                conversation_id=turn.conversation_id,
                message_id=turn.user_message_id,
                source="rules",
                triage_level=final_level.value,
                matched_rules=[f"weak_hit:{w}" for w in rules.weak_words],
                child_age_days=turn.child_age_days,
            )

        await _persist(turn, state, dosing.final_text, final_level, final_reason, degraded)
        yield (
            "done",
            {
                "assistant_message_id": (
                    str(state.assistant_message_id) if state.assistant_message_id else None
                ),
                "triage": final_level.value,
                "degraded_safety": degraded,
            },
        )

        # Passive memory: extraction never delays `done` and is skipped entirely
        # on disconnect/error paths (fail toward extracting nothing).
        _spawn_extraction(turn)

    except (asyncio.CancelledError, GeneratorExit):
        # Client disconnected mid-stream: persist what we have, then re-raise.
        await _persist_best_effort(turn, state, dosing)
        raise
    except Exception as exc:
        logger.exception("chat stream failed")
        with contextlib.suppress(Exception):
            yield ("error", {"code": "upstream_error", "message": str(exc)})
        await _persist_best_effort(turn, state, dosing)
    finally:
        if not classifier_task.done():
            classifier_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await classifier_task


def _spawn_extraction(turn: ChatTurn) -> None:
    """Kick off passive event extraction as a background task.

    The task outlives the SSE generator (strong ref in _background_tasks);
    tests drive chat_turn_events directly and await turn.extraction_task.
    """
    if turn.extractor is None or turn.child_id is None:
        return
    task = asyncio.ensure_future(_run_extraction(turn))
    turn.extraction_task = task
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _run_extraction(turn: ChatTurn) -> None:
    try:
        extracted = await turn.extractor.extract(turn.user_content)
        if not extracted:
            return
        now = datetime.now(UTC)
        async with turn.repo_factory() as repo:
            for item in extracted:
                await repo.add_event(
                    child_id=turn.child_id,
                    user_id=turn.user_id,
                    kind=item.kind,
                    summary=item.summary,
                    occurred_at=now - timedelta(minutes=item.occurred_at_offset_minutes),
                    source="chat_extraction",
                    confirmed=False,
                    message_id=turn.user_message_id,
                )
    except Exception:
        logger.exception("passive memory extraction failed (ignored)")


async def _handle_tag(
    turn: ChatTurn,
    state: _TurnState,
    tag_parser: TriageTagParser,
    dosing: DosingLeakFilter,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Handle the parsed (or malformed) leading triage tag."""
    if tag_parser.malformed:
        state.malformed_tag = True
        state.model_level = TriageLevel.NONE  # treat as none, but flag + stricter filter
        state.extra_matched.append("malformed_tag")
        dosing.escalate()
        await turn.recorder.record(
            user_id=turn.user_id,
            conversation_id=turn.conversation_id,
            message_id=turn.user_message_id,
            source="model_tag",
            triage_level=TriageLevel.NONE.value,
            matched_rules=["malformed_tag"],
            child_age_days=turn.child_age_days,
        )
        return

    state.model_level = tag_parser.level
    state.model_reason = tag_parser.reason
    if tag_parser.level is not None and tag_parser.level != TriageLevel.NONE:
        yield (
            "safety",
            {
                "triage": tag_parser.level.value,
                "reason": tag_parser.reason,
                "source": "model_tag",
            },
        )
        await turn.recorder.record(
            user_id=turn.user_id,
            conversation_id=turn.conversation_id,
            message_id=turn.user_message_id,
            source="model_tag",
            triage_level=tag_parser.level.value,
            matched_rules=[tag_parser.reason] if tag_parser.reason else None,
            child_age_days=turn.child_age_days,
        )


async def _handle_filter_trigger(
    turn: ChatTurn, state: _TurnState
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """A dosing leak was blocked: replace output with the safe redirect + audit."""
    state.filter_triggered = True
    await turn.recorder.record(
        user_id=turn.user_id,
        conversation_id=turn.conversation_id,
        message_id=turn.user_message_id,
        source="output_filter",
        triage_level=TriageLevel.NONE.value,
        matched_rules=["dosing_leak"],
        child_age_days=turn.child_age_days,
    )
    yield ("delta", {"text": SAFE_DOSING_MESSAGE})


def _merge_final(turn: ChatTurn, state: _TurnState) -> tuple[TriageLevel, str | None]:
    """Max severity across the three signal sources; reason follows the winner
    with deterministic priority rules > classifier > model tag on ties."""
    rules = turn.rules_result
    final = merge_levels(rules.level, state.classifier_level, state.model_level)
    reason: str | None = None
    for level, candidate in (
        (rules.level if rules.fired else None, rules.reason),
        (state.classifier_level, state.classifier_reason),
        (state.model_level, state.model_reason),
    ):
        if level is final and candidate:
            reason = candidate
            break
    if reason is None and final == TriageLevel.NONE:
        reason = "general"
    return final, reason


def _weak_hit_floor_applies(
    turn: ChatTurn, state: _TurnState, current: TriageLevel
) -> bool:
    """High-risk words present without a full rule match → see_doctor floor.

    Only raises severity, never lowers it.
    """
    return (
        turn.rules_result.weak_hit
        and not turn.rules_result.fired
        and current.severity < TriageLevel.SEE_DOCTOR.severity
    )


async def _persist(
    turn: ChatTurn,
    state: _TurnState,
    content: str,
    level: TriageLevel,
    reason: str | None,
    degraded: bool,
) -> None:
    if state.persisted:
        return
    state.persisted = True
    try:
        async with turn.repo_factory() as repo:
            message = await repo.add_message(
                conversation_id=turn.conversation_id,
                role="assistant",
                content=content,
                input_mode=turn.input_mode,
                triage_level=level.value,
                triage_reason=reason,
                degraded_safety=degraded,
                model=turn.model,
            )
            await repo.update_conversation_after_message(turn.conversation_id, level)
            state.assistant_message_id = message.id
    except Exception:
        state.persisted = False
        logger.exception("failed to persist assistant message")


async def _persist_best_effort(
    turn: ChatTurn, state: _TurnState, dosing: DosingLeakFilter
) -> None:
    """Persistence path for disconnect/error. Shielded so cancellation of the
    surrounding task cannot abort the write once started."""
    if state.persisted:
        return
    rules = turn.rules_result
    level = merge_levels(rules.level, state.model_level, state.classifier_level)
    if rules.weak_hit and not rules.fired and level.severity < TriageLevel.SEE_DOCTOR.severity:
        level = TriageLevel.SEE_DOCTOR
    _, reason = _merge_final(turn, state)
    # Disconnect before the classifier resolved counts as a failed check.
    degraded = (not rules.fired) and state.classifier_failed
    content = dosing.final_text
    if not content:
        return  # nothing generated yet; the user message is already durable
    persist_task = asyncio.ensure_future(
        _persist(turn, state, content, level, reason, degraded)
    )
    try:
        await asyncio.shield(persist_task)
    except asyncio.CancelledError:
        # Our task is being torn down; the persist task still runs to completion
        # on the event loop.
        if not persist_task.done():
            with contextlib.suppress(Exception):
                await persist_task
    except Exception:
        logger.exception("best-effort persistence failed")
