"""Full SSE pipeline with mocked Claude: event order, safety timing,
severity merging, degraded flag, stickiness, and disconnect persistence."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.ai.chat_service import ChatService
from app.ai.prompt_builder import build_system_blocks
from app.ai.triage import TriageLevel
from app.api.routes.chat import ChatTurn, chat_turn_events
from app.services.safety.rules import evaluate_rules
from tests.conftest import (
    TEST_USER_ID,
    FakeAnthropicClient,
    FakeClassifier,
    build_app,
    classifier_result,
    parse_sse,
)

TAG_NONE = '<triage level="none" reason="general"/>'

TODAY = datetime.now(UTC).date()

BENIGN_CHUNKS = [
    TAG_NONE,
    "Try putting Mia down drowsy but awake, with white noise as loud as her crying. ",
    "Cluster fussing at this hour is exhausting and completely normal at her age. ",
    "You're doing the right things. See how the next stretch goes.",
]


async def _post_chat(app, child_id, content, conversation_id=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={
                "child_id": str(child_id),
                "content": content,
                "conversation_id": str(conversation_id) if conversation_id else None,
            },
        )
    assert response.status_code == 200
    return parse_sse(response.text)


class TestEventOrder:
    async def test_happy_path_start_deltas_done(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        events = await _post_chat(app, child.id, "she won't settle after her feed")

        names = [name for name, _ in events]
        assert names[0] == "start"
        assert names[-1] == "done"
        assert "delta" in names
        assert "safety" not in names  # nothing fired anywhere

        start = events[0][1]
        assert start["conversation_id"]
        assert start["user_message_id"]

        deltas = "".join(d["text"] for name, d in events if name == "delta")
        assert "<triage" not in deltas  # tag stripped
        assert "drowsy but awake" in deltas

        done = events[-1][1]
        assert done["triage"] == "none"
        assert done["degraded_safety"] is False
        assert done["assistant_message_id"]

        # persisted assistant message matches the streamed text
        [assistant] = fake_repo.assistant_messages()
        assert assistant.content == deltas
        assert assistant.triage_level == "none"

    async def test_rules_safety_fires_before_any_delta(self, fake_repo, recorder):
        child = fake_repo.seed_child(birth_date=TODAY - timedelta(days=56))
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        events = await _post_chat(app, child.id, "her rectal temp is 100.6")

        names = [name for name, _ in events]
        assert "safety" in names
        assert names.index("safety") < names.index("delta")
        assert names.index("safety") > names.index("start")

        safety = next(d for name, d in events if name == "safety")
        assert safety == {
            "triage": "emergency",
            "reason": "fever_under_3mo",
            "source": "rules",
        }

        done = events[-1][1]
        assert done["triage"] == "emergency"

        rules_events = [e for e in recorder.events if e["source"] == "rules"]
        assert rules_events and rules_events[0]["triage_level"] == "emergency"
        assert "fever_under_3mo" in rules_events[0]["matched_rules"]

    async def test_model_tag_emits_safety_event(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        chunks = [
            '<triage level="see_doctor" reason="general"/>',
            "Worth mentioning that cough to your pediatrician tomorrow. For tonight, keep her upright a while after feeds.",
        ]
        app = build_app(fake_repo, recorder, chunks=chunks)
        events = await _post_chat(app, child.id, "she has a little cough")

        safety = [d for name, d in events if name == "safety"]
        assert {"triage": "see_doctor", "reason": "general", "source": "model_tag"} in safety
        assert events[-1][1]["triage"] == "see_doctor"


class TestSeverityMerge:
    async def test_client_takes_max_of_repeated_safety_events(self, fake_repo, recorder):
        child = fake_repo.seed_child(birth_date=TODAY - timedelta(days=56))
        chunks = [
            '<triage level="urgent" reason="fever_under_3mo"/>',
            "Call your pediatrician's after-hours line now.",
        ]
        classifier = FakeClassifier(
            classifier_result(TriageLevel.EMERGENCY, ("fever_under_3mo",))
        )
        app = build_app(fake_repo, recorder, chunks=chunks, classifier=classifier)
        events = await _post_chat(app, child.id, "temp 100.8 tonight")

        levels = [d["triage"] for name, d in events if name == "safety"]
        assert "emergency" in levels  # rules + classifier
        assert events[-1][1]["triage"] == "emergency"  # max(rules, classifier, model)

    async def test_classifier_only_escalation(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        classifier = FakeClassifier(classifier_result(TriageLevel.URGENT, ("breathing",)))
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS, classifier=classifier)
        events = await _post_chat(app, child.id, "something is off with how she sounds")

        safety = [d for name, d in events if name == "safety"]
        assert {"triage": "urgent", "reason": "breathing", "source": "classifier"} in safety
        assert events[-1][1]["triage"] == "urgent"
        assert any(e["source"] == "classifier" for e in recorder.events)


class TestDegradedSafety:
    async def test_degraded_when_rules_miss_and_classifier_fails(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        app = build_app(
            fake_repo, recorder, chunks=BENIGN_CHUNKS, classifier=FakeClassifier(None)
        )
        events = await _post_chat(app, child.id, "she keeps waking every 40 minutes")

        done = events[-1][1]
        assert done["degraded_safety"] is True
        [assistant] = fake_repo.assistant_messages()
        assert assistant.degraded_safety is True

    async def test_not_degraded_when_rules_fired(self, fake_repo, recorder):
        child = fake_repo.seed_child(birth_date=TODAY - timedelta(days=56))
        app = build_app(
            fake_repo, recorder, chunks=BENIGN_CHUNKS, classifier=FakeClassifier(None)
        )
        events = await _post_chat(app, child.id, "temp is 101")
        assert events[-1][1]["degraded_safety"] is False


class TestWeakHitFloor:
    async def test_high_risk_word_without_rule_match_floors_to_see_doctor(
        self, fake_repo, recorder
    ):
        child = fake_repo.seed_child(birth_date=TODAY - timedelta(days=243))
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        events = await _post_chat(app, child.id, "worried a fever might be starting")

        done = events[-1][1]
        assert done["triage"] == "see_doctor"
        safety = [d for name, d in events if name == "safety"]
        assert {"triage": "see_doctor", "reason": "general", "source": "rules"} in safety
        assert any(
            e["source"] == "rules"
            and any(m.startswith("weak_hit:") for m in (e.get("matched_rules") or []))
            for e in recorder.events
        )


class TestStickyConversationTriage:
    async def test_emergency_never_downgrades_within_conversation(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        conversation = fake_repo.seed_conversation(child_id=child.id, max_triage="emergency")
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        events = await _post_chat(
            app, child.id, "she's calm now, thank you", conversation_id=conversation.id
        )
        assert events[-1][1]["triage"] == "none"  # message-level triage
        assert conversation.max_triage == "emergency"  # conversation stays sticky


class TestMalformedTag:
    async def test_malformed_tag_treated_as_none_flagged_and_audited(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        chunks = [
            (
                "Put her down in the crib for a minute and take one slow breath yourself. "
                "Then try a fresh diaper and a slow feed in a dim room."
            ),
        ]
        app = build_app(fake_repo, recorder, chunks=chunks)
        events = await _post_chat(app, child.id, "she won't stop crying")

        done = events[-1][1]
        assert done["triage"] == "none"
        deltas = "".join(d["text"] for name, d in events if name == "delta")
        assert "Put her down in the crib" in deltas
        assert any(
            e["source"] == "model_tag" and "malformed_tag" in (e.get("matched_rules") or [])
            for e in recorder.events
        )


class TestErrorEvent:
    async def test_upstream_failure_emits_error_event(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)

        class FailingChatService:
            model = "test-model"

            async def stream_text(self, *, system, messages):
                yield TAG_NONE + "Star"
                raise RuntimeError("anthropic 529")

        app.state.chat_service = FailingChatService()
        events = await _post_chat(app, child.id, "hello")
        names = [name for name, _ in events]
        assert "error" in names
        error = next(d for name, d in events if name == "error")
        assert error["code"] == "upstream_error"


class TestDisconnectPersistence:
    async def test_assistant_message_persisted_when_client_disconnects(
        self, fake_repo, recorder
    ):
        child = fake_repo.seed_child()
        conversation = fake_repo.seed_conversation(child_id=child.id)
        user_message = await fake_repo.add_message(
            conversation_id=conversation.id, role="user", content="she won't settle"
        )

        @asynccontextmanager
        async def fake_factory():
            yield fake_repo

        long_chunk = (
            "Try a slow, paced feed in a dim room with white noise on. "
            "This stretch of night is the hardest one and it does pass. " * 3
        )
        turn = ChatTurn(
            user_id=TEST_USER_ID,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            child_age_days=56,
            input_mode="text",
            rules_result=evaluate_rules("she won't settle", 56),
            system_blocks=build_system_blocks("<child_context>test</child_context>"),
            messages=[{"role": "user", "content": "she won't settle"}],
            chat_service=ChatService(
                client=FakeAnthropicClient([TAG_NONE, long_chunk, long_chunk]),
                model="test-model",
            ),
            classifier=FakeClassifier(classifier_result(TriageLevel.NONE)),
            repo_factory=fake_factory,
            recorder=recorder,
            user_content="she won't settle",
        )

        generator = chat_turn_events(turn)
        deltas_seen = 0
        async for event, _data in generator:
            if event == "delta":
                deltas_seen += 1
                if deltas_seen >= 1:
                    break
        # Simulate the client disconnecting: close the generator mid-stream.
        await generator.aclose()

        assistants = fake_repo.assistant_messages()
        assert len(assistants) == 1, "assistant message must be persisted on disconnect"
        assert "paced feed" in assistants[0].content
        assert assistants[0].triage_level == "none"
        # Classifier never resolved before disconnect → flagged for review.
        assert assistants[0].degraded_safety is True


class TestVoiceInputMode:
    async def test_input_mode_voice_persisted(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/chat",
                json={
                    "child_id": str(child.id),
                    "content": "transcribed voice text",
                    "input_mode": "voice",
                },
            )
        assert response.status_code == 200
        user_messages = [m for m in fake_repo.messages if m.role == "user"]
        assert user_messages[0].input_mode == "voice"


class TestChildValidation:
    async def test_unknown_child_404(self, fake_repo, recorder):
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/chat",
                json={
                    "child_id": "99999999-9999-9999-9999-999999999999",
                    "content": "hello",
                },
            )
        assert response.status_code == 404


@pytest.mark.eval_live
class TestLiveEvalPlaceholder:
    """Live-model golden safety set lands in tests/evals (Phase 1c)."""

    async def test_placeholder(self):
        pytest.skip("live evals require ANTHROPIC_API_KEY and network")
