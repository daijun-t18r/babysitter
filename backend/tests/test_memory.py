"""Passive memory: extractor unit behavior, chat wiring, and the
unconfirmed-never-injected invariant."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx

from app.ai.chat_service import ChatService
from app.ai.prompt_builder import build_child_context, build_system_blocks
from app.ai.triage import TriageLevel
from app.api.routes.chat import ChatTurn, chat_turn_events
from app.services.memory import ExtractedEvent, MemoryExtractor
from app.services.safety.rules import evaluate_rules
from tests.conftest import (
    TEST_USER_ID,
    FakeAnthropicClient,
    FakeClassifier,
    FakeClassifierClient,
    FakeExtractor,
    FakeRecorder,
    build_app,
    classifier_result,
)

TAG_NONE = '<triage level="none" reason="general"/>'
BENIGN_CHUNKS = [TAG_NONE, "Try a snug swaddle and loud white noise."]


# --- extractor unit behavior ----------------------------------------------------


class TestMemoryExtractor:
    async def test_valid_json(self):
        client = FakeClassifierClient(
            {
                "events": [
                    {
                        "kind": "feeding",
                        "summary": "breastfed ~15 min",
                        "occurred_at_offset_minutes": 20,
                    }
                ]
            }
        )
        extractor = MemoryExtractor(client=client, model="test-model")
        events = await extractor.extract("I fed her 20 minutes ago and she's still crying")
        assert events == [
            ExtractedEvent(
                kind="feeding", summary="breastfed ~15 min", occurred_at_offset_minutes=20
            )
        ]

    async def test_code_fences_tolerated(self):
        client = FakeClassifierClient(
            '```json\n{"events": [{"kind": "sleep", "summary": "woke up crying", '
            '"occurred_at_offset_minutes": 5}]}\n```'
        )
        extractor = MemoryExtractor(client=client, model="test-model")
        events = await extractor.extract("he just woke up crying")
        assert len(events) == 1
        assert events[0].kind == "sleep"

    async def test_malformed_json_returns_empty(self):
        extractor = MemoryExtractor(
            client=FakeClassifierClient("not json at all"), model="test-model"
        )
        assert await extractor.extract("anything") == []

    async def test_upstream_error_returns_empty(self):
        extractor = MemoryExtractor(
            client=FakeClassifierClient({}, raises=True), model="test-model"
        )
        assert await extractor.extract("anything") == []

    async def test_timeout_returns_empty(self):
        client = FakeClassifierClient({"events": []}, delay_s=0.2)
        extractor = MemoryExtractor(client=client, model="test-model", timeout_s=0.05)
        assert await extractor.extract("anything") == []

    async def test_unknown_kind_and_empty_summary_skipped(self):
        client = FakeClassifierClient(
            {
                "events": [
                    {"kind": "bath", "summary": "took a bath"},
                    {"kind": "feeding", "summary": "   "},
                    {"kind": "diaper", "summary": "wet diaper changed"},
                ]
            }
        )
        extractor = MemoryExtractor(client=client, model="test-model")
        events = await extractor.extract("changed a wet diaper")
        assert [e.kind for e in events] == ["diaper"]

    async def test_negative_offset_clamped_and_capped_at_five(self):
        client = FakeClassifierClient(
            {
                "events": [
                    {"kind": "note", "summary": f"n{i}", "occurred_at_offset_minutes": -30}
                    for i in range(8)
                ]
            }
        )
        extractor = MemoryExtractor(client=client, model="test-model")
        events = await extractor.extract("busy night")
        assert len(events) == 5
        assert all(e.occurred_at_offset_minutes == 0 for e in events)

    async def test_prompt_uses_only_the_parent_message(self):
        captured: dict = {}

        class CapturingClient:
            def __init__(self):
                self.messages = self

            async def create(self, **kwargs):
                captured.update(kwargs)
                from types import SimpleNamespace

                return SimpleNamespace(
                    content=[SimpleNamespace(text='{"events": []}')]
                )

        extractor = MemoryExtractor(client=CapturingClient(), model="test-model")
        await extractor.extract("I fed her an hour ago")
        assert captured["messages"] == [
            {"role": "user", "content": "Parent message: I fed her an hour ago"}
        ]


# --- chat wiring ---------------------------------------------------------------


def _make_turn(fake_repo, extractor, content="I fed her 30 minutes ago", child_id=None):
    @asynccontextmanager
    async def factory():
        yield fake_repo

    child_context = build_child_context(
        name="Mia", birth_date=datetime.now(UTC).date() - timedelta(days=56)
    )
    return ChatTurn(
        user_id=TEST_USER_ID,
        conversation_id=__import__("uuid").uuid4(),
        user_message_id=__import__("uuid").uuid4(),
        child_age_days=56,
        input_mode="text",
        rules_result=evaluate_rules(content, 56),
        system_blocks=build_system_blocks(child_context),
        messages=[{"role": "user", "content": content}],
        chat_service=ChatService(client=FakeAnthropicClient(BENIGN_CHUNKS), model="test-model"),
        classifier=FakeClassifier(classifier_result(TriageLevel.NONE)),
        repo_factory=factory,
        recorder=FakeRecorder(),
        user_content=content,
        child_id=child_id,
        extractor=extractor,
    )


class TestExtractionWiring:
    async def test_extraction_persists_unconfirmed_events(self, fake_repo):
        child = fake_repo.seed_child()
        extractor = FakeExtractor(
            [ExtractedEvent(kind="feeding", summary="fed ~30 min ago", occurred_at_offset_minutes=30)]
        )
        turn = _make_turn(fake_repo, extractor, child_id=child.id)

        events = [e async for e in chat_turn_events(turn)]
        assert events[-1][0] == "done"
        assert turn.extraction_task is not None
        await turn.extraction_task

        pending = fake_repo.pending_events()
        assert len(pending) == 1
        assert pending[0].confirmed is False
        assert pending[0].kind == "feeding"
        assert pending[0].message_id == turn.user_message_id
        # occurred_at respects the stated offset
        assert pending[0].occurred_at < datetime.now(UTC) - timedelta(minutes=29)
        assert extractor.calls == [turn.user_content]

    async def test_no_extractor_means_no_task(self, fake_repo):
        child = fake_repo.seed_child()
        turn = _make_turn(fake_repo, extractor=None, child_id=child.id)
        [e async for e in chat_turn_events(turn)]
        assert turn.extraction_task is None

    async def test_extractor_failure_never_breaks_the_stream(self, fake_repo):
        child = fake_repo.seed_child()

        class ExplodingExtractor:
            async def extract(self, content):
                raise RuntimeError("boom")

        turn = _make_turn(fake_repo, ExplodingExtractor(), child_id=child.id)
        events = [e async for e in chat_turn_events(turn)]
        assert events[-1][0] == "done"
        await turn.extraction_task  # swallowed inside _run_extraction
        assert fake_repo.pending_events() == []


# --- the invariant: unconfirmed events never reach the prompt -------------------


class TestUnconfirmedNeverInjected:
    async def test_route_injects_confirmed_only(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        now = datetime.now(UTC)
        fake_repo.seed_event(
            child_id=child.id,
            summary="bottle 4 oz",
            confirmed=True,
            occurred_at=now - timedelta(minutes=90),
        )
        fake_repo.seed_event(
            child_id=child.id,
            summary="UNCONFIRMED_MARKER",
            confirmed=False,
            occurred_at=now - timedelta(minutes=10),
        )
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/chat",
                json={"child_id": str(child.id), "content": "she's crying again"},
            )
        assert response.status_code == 200

        stream_calls = app.state.chat_service._get_client().messages.stream_calls
        assert len(stream_calls) == 1
        system_text = "\n".join(block["text"] for block in stream_calls[0]["system"])
        assert "bottle 4 oz" in system_text
        assert "UNCONFIRMED_MARKER" not in system_text

    async def test_repo_query_filters_unconfirmed(self, fake_repo):
        child = fake_repo.seed_child()
        now = datetime.now(UTC)
        fake_repo.seed_event(child_id=child.id, summary="confirmed one", confirmed=True)
        fake_repo.seed_event(child_id=child.id, summary="pending one", confirmed=False)
        events = await fake_repo.list_confirmed_events_since(
            child.id, TEST_USER_ID, since=now - timedelta(hours=24)
        )
        assert [e.summary for e in events] == ["confirmed one"]
