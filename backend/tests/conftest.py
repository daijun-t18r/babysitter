"""Shared offline fixtures: no network, no database.

The app's seams (auth dependency, repo factory, anthropic-shaped clients,
safety recorder) are all replaced with in-memory fakes.
"""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Self

import pytest

from app.ai.chat_service import ChatService
from app.ai.triage import TriageLevel
from app.api import deps
from app.core import auth as auth_module
from app.core.auth import AuthenticatedUser
from app.main import create_app
from app.services.safety.classifier import ClassifierResult

TEST_USER_ID = "11111111-1111-1111-1111-111111111111"
TEST_USER = AuthenticatedUser(user_id=TEST_USER_ID, email="parent@example.com")

_SEVERITY = {level: level.severity for level in TriageLevel}


def utcnow() -> datetime:
    return datetime.now(UTC)


# --- in-memory repo ------------------------------------------------------------


class FakeRepo:
    def __init__(self) -> None:
        self.profiles: dict[str, Any] = {}
        self.children: dict[str, Any] = {}
        self.conversations: dict[str, Any] = {}
        self.messages: list[Any] = []
        self.events: dict[str, Any] = {}

    # seeding helpers -----------------------------------------------------------

    def seed_profile(self, user_id: str = TEST_USER_ID, **kw: Any) -> Any:
        profile = SimpleNamespace(
            id=uuid.UUID(user_id),
            display_name=kw.get("display_name", "Test Parent"),
            phone=kw.get("phone"),
            disclaimer_accepted_at=kw.get("disclaimer_accepted_at"),
            created_at=utcnow(),
        )
        self.profiles[str(profile.id)] = profile
        return profile

    def seed_child(
        self,
        user_id: str = TEST_USER_ID,
        birth_date: date | None = None,
        **kw: Any,
    ) -> Any:
        child = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            name=kw.get("name", "Mia"),
            birth_date=birth_date or (datetime.now(UTC).date() - timedelta(days=56)),
            due_date=kw.get("due_date"),
            feeding_type=kw.get("feeding_type", "breast"),
            notes=kw.get("notes"),
            pediatrician_name=kw.get("pediatrician_name"),
            pediatrician_phone=kw.get("pediatrician_phone"),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self.children[str(child.id)] = child
        return child

    def seed_conversation(self, user_id: str = TEST_USER_ID, **kw: Any) -> Any:
        conversation = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            child_id=kw.get("child_id"),
            title=kw.get("title"),
            max_triage=kw.get("max_triage", "none"),
            created_at=utcnow(),
            last_message_at=utcnow(),
        )
        self.conversations[str(conversation.id)] = conversation
        return conversation

    def seed_event(
        self,
        child_id: Any,
        user_id: str = TEST_USER_ID,
        occurred_at: datetime | None = None,
        **kw: Any,
    ) -> Any:
        event = SimpleNamespace(
            id=uuid.uuid4(),
            child_id=child_id,
            user_id=uuid.UUID(user_id),
            kind=kw.get("kind", "feeding"),
            summary=kw.get("summary", "breastfed ~15 min"),
            occurred_at=occurred_at or utcnow(),
            source=kw.get("source", "chat_extraction"),
            confirmed=kw.get("confirmed", False),
            message_id=kw.get("message_id"),
            metadata_json=kw.get("metadata", {}),
            created_at=kw.get("created_at", utcnow()),
        )
        self.events[str(event.id)] = event
        return event

    # repo surface --------------------------------------------------------------

    async def get_profile(self, user_id: Any) -> Any:
        return self.profiles.get(str(user_id))

    async def list_children(self, user_id: Any) -> list[Any]:
        return [c for c in self.children.values() if str(c.user_id) == str(user_id)]

    async def get_child(self, child_id: Any, user_id: Any) -> Any:
        child = self.children.get(str(child_id))
        if child is None or str(child.user_id) != str(user_id):
            return None
        return child

    async def create_child(self, user_id: Any, **fields: Any) -> Any:
        return self.seed_child(user_id=str(user_id), **fields)

    async def update_child(self, child_id: Any, user_id: Any, **fields: Any) -> Any:
        child = await self.get_child(child_id, user_id)
        if child is None:
            return None
        for key, value in fields.items():
            setattr(child, key, value)
        child.updated_at = utcnow()
        return child

    async def list_conversations(self, user_id: Any, limit: int = 20) -> list[Any]:
        conversations = [
            c for c in self.conversations.values() if str(c.user_id) == str(user_id)
        ]
        conversations.sort(key=lambda c: c.last_message_at, reverse=True)
        return conversations[:limit]

    async def get_conversation(self, conversation_id: Any, user_id: Any) -> Any:
        conversation = self.conversations.get(str(conversation_id))
        if conversation is None or str(conversation.user_id) != str(user_id):
            return None
        return conversation

    async def create_conversation(
        self, user_id: Any, child_id: Any, title: str | None = None
    ) -> Any:
        return self.seed_conversation(user_id=str(user_id), child_id=child_id, title=title)

    async def list_messages(self, conversation_id: Any, limit: int | None = None) -> list[Any]:
        messages = [m for m in self.messages if str(m.conversation_id) == str(conversation_id)]
        if limit is not None:
            messages = messages[-limit:]
        return messages

    async def add_message(self, conversation_id: Any, role: str, content: str, **kw: Any) -> Any:
        message = SimpleNamespace(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            input_mode=kw.get("input_mode", "text"),
            triage_level=kw.get("triage_level", "none"),
            triage_reason=kw.get("triage_reason"),
            degraded_safety=kw.get("degraded_safety", False),
            model=kw.get("model"),
            input_tokens=kw.get("input_tokens"),
            output_tokens=kw.get("output_tokens"),
            created_at=utcnow(),
        )
        self.messages.append(message)
        return message

    async def update_conversation_after_message(
        self, conversation_id: Any, triage: TriageLevel
    ) -> None:
        conversation = self.conversations.get(str(conversation_id))
        if conversation is None:
            return
        if triage.severity > TriageLevel(conversation.max_triage).severity:
            conversation.max_triage = triage.value
        conversation.last_message_at = utcnow()

    # events (passive memory) ---------------------------------------------------

    async def add_event(
        self,
        *,
        child_id: Any,
        user_id: Any,
        kind: str,
        summary: str,
        occurred_at: datetime,
        source: str = "chat_extraction",
        confirmed: bool = False,
        message_id: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return self.seed_event(
            child_id=child_id,
            user_id=str(user_id),
            occurred_at=occurred_at,
            kind=kind,
            summary=summary,
            source=source,
            confirmed=confirmed,
            message_id=message_id,
            metadata=metadata or {},
        )

    async def list_pending_events(
        self, user_id: Any, child_id: Any, limit: int = 20
    ) -> list[Any]:
        events = [
            e
            for e in self.events.values()
            if str(e.user_id) == str(user_id)
            and str(e.child_id) == str(child_id)
            and not e.confirmed
        ]
        events.sort(key=lambda e: e.created_at, reverse=True)
        return events[:limit]

    async def get_event(self, event_id: Any, user_id: Any) -> Any:
        event = self.events.get(str(event_id))
        if event is None or str(event.user_id) != str(user_id):
            return None
        return event

    async def confirm_events(self, event_ids: list[Any], user_id: Any) -> int:
        confirmed = 0
        for event_id in event_ids:
            event = await self.get_event(event_id, user_id)
            if event is not None and not event.confirmed:
                event.confirmed = True
                confirmed += 1
        return confirmed

    async def delete_event(self, event_id: Any, user_id: Any) -> bool:
        event = await self.get_event(event_id, user_id)
        if event is None or event.confirmed:
            return False
        del self.events[str(event_id)]
        return True

    async def list_confirmed_events_since(
        self, child_id: Any, user_id: Any, since: datetime, limit: int = 10
    ) -> list[Any]:
        events = [
            e
            for e in self.events.values()
            if str(e.child_id) == str(child_id)
            and str(e.user_id) == str(user_id)
            and e.confirmed
            and e.occurred_at >= since
        ]
        events.sort(key=lambda e: e.occurred_at, reverse=True)
        return events[:limit]

    async def list_confirmed_events(
        self, user_id: Any, child_id: Any, limit: int = 100
    ) -> list[Any]:
        events = [
            e
            for e in self.events.values()
            if str(e.user_id) == str(user_id)
            and str(e.child_id) == str(child_id)
            and e.confirmed
        ]
        events.sort(key=lambda e: e.occurred_at, reverse=True)
        return events[:limit]

    async def list_confirmed_events_between(
        self, user_id: Any, start: datetime, end: datetime, limit: int = 40
    ) -> list[Any]:
        events = [
            e
            for e in self.events.values()
            if str(e.user_id) == str(user_id) and e.confirmed and start <= e.occurred_at < end
        ]
        events.sort(key=lambda e: e.occurred_at)
        return events[:limit]

    async def list_user_messages_between(
        self, user_id: Any, start: datetime, end: datetime, limit: int = 200
    ) -> list[Any]:
        own_conversations = {
            str(c.id) for c in self.conversations.values() if str(c.user_id) == str(user_id)
        }
        messages = [
            m
            for m in self.messages
            if str(m.conversation_id) in own_conversations
            and start <= m.created_at < end
        ]
        messages.sort(key=lambda m: m.created_at)
        return messages[:limit]

    # assertions ----------------------------------------------------------------

    def assistant_messages(self) -> list[Any]:
        return [m for m in self.messages if m.role == "assistant"]

    def pending_events(self) -> list[Any]:
        return [e for e in self.events.values() if not e.confirmed]


# --- anthropic-shaped fakes ----------------------------------------------------


class _FakeMessageStream:
    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    @property
    def text_stream(self) -> Any:
        async def gen() -> Any:
            for chunk in self._chunks:
                yield chunk

        return gen()


class _FakeMessages:
    def __init__(self, chunks: list[str]):
        self._chunks = chunks
        self.stream_calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> _FakeMessageStream:
        self.stream_calls.append(kwargs)
        return _FakeMessageStream(self._chunks)


class FakeAnthropicClient:
    """Just enough surface for ChatService: client.messages.stream(...)."""

    def __init__(self, chunks: list[str]):
        self.messages = _FakeMessages(chunks)


class FakeClassifierClient:
    """Just enough surface for SafetyClassifier: client.messages.create(...)."""

    def __init__(self, payload: Any, delay_s: float = 0.0, raises: bool = False):
        self._payload = payload
        self._delay_s = delay_s
        self._raises = raises
        self.messages = self

    async def create(self, **kwargs: Any) -> Any:
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._raises:
            raise RuntimeError("classifier upstream down")
        text = self._payload if isinstance(self._payload, str) else json.dumps(self._payload)
        return SimpleNamespace(content=[SimpleNamespace(text=text)])


class FakeClassifier:
    """Duck-typed drop-in for SafetyClassifier at the chat-route seam."""

    def __init__(self, result: ClassifierResult | None):
        self._result = result
        self.calls: list[tuple[str, int | None]] = []

    async def classify(self, content: str, age_days: int | None) -> ClassifierResult | None:
        self.calls.append((content, age_days))
        return self._result


class FakeRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


def classifier_result(level: TriageLevel, reasons: tuple[str, ...] = ()) -> ClassifierResult:
    return ClassifierResult(
        level=level, reasons=reasons, raw={"triage": level.value, "reasons": list(reasons)}
    )


# --- app assembly --------------------------------------------------------------


class FakeExtractor:
    """Duck-typed drop-in for MemoryExtractor at the chat-route seam."""

    def __init__(self, events: list[Any] | None = None):
        self._events = events or []
        self.calls: list[str] = []

    async def extract(self, user_content: str) -> list[Any]:
        self.calls.append(user_content)
        return self._events


def build_app(
    fake_repo: FakeRepo,
    recorder: FakeRecorder,
    chunks: list[str] | None = None,
    classifier: Any | None = None,
    extractor: Any | None = None,
    summarizer_client: Any | None = None,
) -> Any:
    from app.services.memory import MorningSummarizer

    app = create_app(
        chat_service=ChatService(client=FakeAnthropicClient(chunks or []), model="test-model"),
        classifier=classifier or FakeClassifier(classifier_result(TriageLevel.NONE)),
        safety_recorder=recorder,  # type: ignore[arg-type]
        memory_extractor=extractor or FakeExtractor(),
        morning_summarizer=MorningSummarizer(
            client=summarizer_client
            or FakeClassifierClient("Rough night, but you handled it. One tip for tonight: keep the swaddle snug."),
            model="test-model",
        ),
    )

    @asynccontextmanager
    async def fake_factory():
        yield fake_repo

    app.dependency_overrides[auth_module.get_current_user] = lambda: TEST_USER
    app.dependency_overrides[deps.get_repo] = lambda: fake_repo
    app.dependency_overrides[deps.get_repo_factory] = lambda: fake_factory
    return app


@pytest.fixture
def fake_repo() -> FakeRepo:
    repo = FakeRepo()
    repo.seed_profile()
    return repo


@pytest.fixture
def recorder() -> FakeRecorder:
    return FakeRecorder()


# --- SSE parsing ---------------------------------------------------------------


def parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = None
        data = None
        for line in block.splitlines():
            line = line.strip("\r")
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if event_name is not None:
            events.append((event_name, data))
    return events
