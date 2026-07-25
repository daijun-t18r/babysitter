"""Plain-dict serializers (attribute-based, so test fakes work unchanged)."""

from typing import Any


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def serialize_profile(profile: Any) -> dict[str, Any]:
    return {
        "id": str(profile.id),
        "display_name": profile.display_name,
        "phone": profile.phone,
        "disclaimer_accepted_at": _iso(profile.disclaimer_accepted_at),
        "created_at": _iso(profile.created_at),
    }


def serialize_child(child: Any) -> dict[str, Any]:
    return {
        "id": str(child.id),
        "name": child.name,
        "birth_date": _iso(child.birth_date),
        "due_date": _iso(child.due_date),
        "feeding_type": child.feeding_type,
        "notes": child.notes,
        "pediatrician_name": child.pediatrician_name,
        "pediatrician_phone": child.pediatrician_phone,
        "created_at": _iso(child.created_at),
        "updated_at": _iso(child.updated_at),
    }


def serialize_conversation(conversation: Any) -> dict[str, Any]:
    return {
        "id": str(conversation.id),
        "child_id": str(conversation.child_id) if conversation.child_id else None,
        "title": conversation.title,
        "max_triage": conversation.max_triage,
        "created_at": _iso(conversation.created_at),
        "last_message_at": _iso(conversation.last_message_at),
    }


def serialize_event(event: Any) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "child_id": str(event.child_id),
        "kind": event.kind,
        "summary": event.summary,
        "occurred_at": _iso(event.occurred_at),
        "source": event.source,
        "confirmed": event.confirmed,
        "message_id": str(event.message_id) if event.message_id else None,
        "created_at": _iso(event.created_at),
    }


def serialize_message(message: Any) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "role": message.role,
        "content": message.content,
        "input_mode": message.input_mode,
        "triage_level": message.triage_level,
        "triage_reason": message.triage_reason,
        "degraded_safety": message.degraded_safety,
        "created_at": _iso(message.created_at),
    }
