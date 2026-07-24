"""Query helpers over an RLS-scoped session.

RLS is the primary access control; explicit user_id filters are kept as
defense in depth. Tests substitute an in-memory fake with the same surface.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.triage import TriageLevel
from app.db.models import Child, Conversation, Event, Message, Profile, utcnow


def _uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


class Repo:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_profile(self, user_id: uuid.UUID | str) -> Profile | None:
        return await self._session.get(Profile, _uuid(user_id))

    async def list_children(self, user_id: uuid.UUID | str) -> list[Child]:
        result = await self._session.execute(
            select(Child).where(Child.user_id == _uuid(user_id)).order_by(Child.created_at)
        )
        return list(result.scalars())

    async def get_child(
        self, child_id: uuid.UUID | str, user_id: uuid.UUID | str
    ) -> Child | None:
        result = await self._session.execute(
            select(Child).where(Child.id == _uuid(child_id), Child.user_id == _uuid(user_id))
        )
        return result.scalar_one_or_none()

    async def create_child(self, user_id: uuid.UUID | str, **fields: Any) -> Child:
        child = Child(user_id=_uuid(user_id), **fields)
        self._session.add(child)
        await self._session.flush()
        return child

    async def update_child(
        self, child_id: uuid.UUID | str, user_id: uuid.UUID | str, **fields: Any
    ) -> Child | None:
        child = await self.get_child(child_id, user_id)
        if child is None:
            return None
        for key, value in fields.items():
            setattr(child, key, value)
        child.updated_at = utcnow()
        await self._session.flush()
        return child

    async def list_conversations(
        self, user_id: uuid.UUID | str, limit: int = 20
    ) -> list[Conversation]:
        result = await self._session.execute(
            select(Conversation)
            .where(Conversation.user_id == _uuid(user_id))
            .order_by(Conversation.last_message_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def get_conversation(
        self, conversation_id: uuid.UUID | str, user_id: uuid.UUID | str
    ) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.id == _uuid(conversation_id),
                Conversation.user_id == _uuid(user_id),
            )
        )
        return result.scalar_one_or_none()

    async def create_conversation(
        self,
        user_id: uuid.UUID | str,
        child_id: uuid.UUID | str | None,
        title: str | None = None,
    ) -> Conversation:
        conversation = Conversation(
            user_id=_uuid(user_id),
            child_id=_uuid(child_id) if child_id else None,
            title=title,
        )
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def list_messages(
        self, conversation_id: uuid.UUID | str, limit: int | None = None
    ) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == _uuid(conversation_id))
            .order_by(Message.created_at)
        )
        result = await self._session.execute(stmt)
        messages = list(result.scalars())
        if limit is not None:
            messages = messages[-limit:]
        return messages

    async def add_message(
        self,
        conversation_id: uuid.UUID | str,
        role: str,
        content: str,
        input_mode: str = "text",
        triage_level: str = "none",
        triage_reason: str | None = None,
        degraded_safety: bool = False,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> Message:
        message = Message(
            conversation_id=_uuid(conversation_id),
            role=role,
            content=content,
            input_mode=input_mode,
            triage_level=triage_level,
            triage_reason=triage_reason,
            degraded_safety=degraded_safety,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def update_conversation_after_message(
        self, conversation_id: uuid.UUID | str, triage: TriageLevel
    ) -> None:
        """Bump last_message_at and raise max_triage (sticky: never downgrades)."""
        result = await self._session.execute(
            select(Conversation).where(Conversation.id == _uuid(conversation_id))
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            return
        current = TriageLevel(conversation.max_triage)
        if triage.severity > current.severity:
            conversation.max_triage = triage.value
        conversation.last_message_at = utcnow()
        await self._session.flush()

    # events (passive memory) ---------------------------------------------------

    async def add_event(
        self,
        *,
        child_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
        kind: str,
        summary: str,
        occurred_at: datetime,
        source: str = "chat_extraction",
        confirmed: bool = False,
        message_id: uuid.UUID | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            child_id=_uuid(child_id),
            user_id=_uuid(user_id),
            kind=kind,
            summary=summary,
            occurred_at=occurred_at,
            source=source,
            confirmed=confirmed,
            message_id=_uuid(message_id) if message_id else None,
            metadata_json=metadata or {},
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_pending_events(
        self, user_id: uuid.UUID | str, child_id: uuid.UUID | str, limit: int = 20
    ) -> list[Event]:
        result = await self._session.execute(
            select(Event)
            .where(
                Event.user_id == _uuid(user_id),
                Event.child_id == _uuid(child_id),
                Event.confirmed.is_(False),
            )
            .order_by(Event.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def get_event(
        self, event_id: uuid.UUID | str, user_id: uuid.UUID | str
    ) -> Event | None:
        result = await self._session.execute(
            select(Event).where(Event.id == _uuid(event_id), Event.user_id == _uuid(user_id))
        )
        return result.scalar_one_or_none()

    async def confirm_events(
        self, event_ids: list[uuid.UUID | str], user_id: uuid.UUID | str
    ) -> int:
        confirmed = 0
        for event_id in event_ids:
            event = await self.get_event(event_id, user_id)
            if event is not None and not event.confirmed:
                event.confirmed = True
                confirmed += 1
        await self._session.flush()
        return confirmed

    async def delete_event(
        self, event_id: uuid.UUID | str, user_id: uuid.UUID | str
    ) -> bool:
        """Dismiss = delete; only unconfirmed events are deletable."""
        event = await self.get_event(event_id, user_id)
        if event is None or event.confirmed:
            return False
        await self._session.delete(event)
        await self._session.flush()
        return True

    async def list_confirmed_events_since(
        self,
        child_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
        since: datetime,
        limit: int = 10,
    ) -> list[Event]:
        """Newest first. Only confirmed events — the never-inject-unconfirmed
        invariant is enforced here at the query layer."""
        result = await self._session.execute(
            select(Event)
            .where(
                Event.child_id == _uuid(child_id),
                Event.user_id == _uuid(user_id),
                Event.confirmed.is_(True),
                Event.occurred_at >= since,
            )
            .order_by(Event.occurred_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def list_confirmed_events(
        self, user_id: uuid.UUID | str, child_id: uuid.UUID | str, limit: int = 100
    ) -> list[Event]:
        result = await self._session.execute(
            select(Event)
            .where(
                Event.user_id == _uuid(user_id),
                Event.child_id == _uuid(child_id),
                Event.confirmed.is_(True),
            )
            .order_by(Event.occurred_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def list_confirmed_events_between(
        self,
        user_id: uuid.UUID | str,
        start: datetime,
        end: datetime,
        limit: int = 40,
    ) -> list[Event]:
        result = await self._session.execute(
            select(Event)
            .where(
                Event.user_id == _uuid(user_id),
                Event.confirmed.is_(True),
                Event.occurred_at >= start,
                Event.occurred_at < end,
            )
            .order_by(Event.occurred_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def list_user_messages_between(
        self, user_id: uuid.UUID | str, start: datetime, end: datetime, limit: int = 200
    ) -> list[Message]:
        """All messages in the user's conversations within [start, end), chronological."""
        result = await self._session.execute(
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.user_id == _uuid(user_id),
                Message.created_at >= start,
                Message.created_at < end,
            )
            .order_by(Message.created_at)
            .limit(limit)
        )
        return list(result.scalars())
