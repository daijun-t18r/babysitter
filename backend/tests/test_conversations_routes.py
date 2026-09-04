"""Conversation endpoints: list and detail."""

import uuid

import httpx

from tests.conftest import build_app


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class TestListConversations:
    async def test_lists_own_conversations_newest_first_and_applies_limit(
        self, fake_repo, recorder
    ):
        first = fake_repo.seed_conversation(title="first")
        second = fake_repo.seed_conversation(title="second")
        second.last_message_at = second.last_message_at.replace(
            year=second.last_message_at.year + 1
        )
        fake_repo.seed_conversation(user_id="22222222-2222-2222-2222-222222222222", title="other")
        app = build_app(fake_repo, recorder)

        async with _client(app) as client:
            response = await client.get("/api/v1/conversations", params={"limit": 1})

        assert response.status_code == 200
        payload = response.json()["conversations"]
        assert [conversation["title"] for conversation in payload] == ["second"]
        assert payload[0]["id"] == str(second.id)
        assert payload[0]["child_id"] is None
        assert payload[0]["max_triage"] == "none"

    async def test_ignores_other_users_conversations(self, fake_repo, recorder):
        fake_repo.seed_conversation(user_id="22222222-2222-2222-2222-222222222222", title="other")
        app = build_app(fake_repo, recorder)

        async with _client(app) as client:
            response = await client.get("/api/v1/conversations")

        assert response.status_code == 200
        assert response.json() == {"conversations": []}


class TestGetConversation:
    async def test_returns_conversation_with_messages(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        conversation = fake_repo.seed_conversation(child_id=child.id, title="check in")
        first = await fake_repo.add_message(conversation.id, "user", "hello")
        second = await fake_repo.add_message(conversation.id, "assistant", "hi")
        app = build_app(fake_repo, recorder)

        async with _client(app) as client:
            response = await client.get(f"/api/v1/conversations/{conversation.id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == str(conversation.id)
        assert payload["child_id"] == str(child.id)
        assert payload["title"] == "check in"
        assert payload["messages"] == [
            {
                "id": str(first.id),
                "conversation_id": str(conversation.id),
                "role": "user",
                "content": "hello",
                "input_mode": "text",
                "triage_level": "none",
                "triage_reason": None,
                "degraded_safety": False,
                "created_at": first.created_at.isoformat(),
            },
            {
                "id": str(second.id),
                "conversation_id": str(conversation.id),
                "role": "assistant",
                "content": "hi",
                "input_mode": "text",
                "triage_level": "none",
                "triage_reason": None,
                "degraded_safety": False,
                "created_at": second.created_at.isoformat(),
            },
        ]

    async def test_missing_conversation_returns_404(self, fake_repo, recorder):
        app = build_app(fake_repo, recorder)

        async with _client(app) as client:
            response = await client.get(f"/api/v1/conversations/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json()["detail"] == "Conversation not found"
