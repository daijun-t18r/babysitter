"""Event endpoints: pending list, confirm, batch confirm, dismiss, ownership."""

import uuid

import httpx

from tests.conftest import build_app

OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class TestPendingList:
    async def test_lists_own_unconfirmed_newest_first(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        fake_repo.seed_event(child_id=child.id, summary="older", confirmed=False)
        newer = fake_repo.seed_event(child_id=child.id, summary="newer", confirmed=False)
        newer.created_at = newer.created_at.replace(year=newer.created_at.year + 1)
        fake_repo.seed_event(child_id=child.id, summary="confirmed", confirmed=True)
        app = build_app(fake_repo, recorder)

        async with _client(app) as client:
            response = await client.get(
                "/api/v1/events/pending", params={"child_id": str(child.id)}
            )
        assert response.status_code == 200
        summaries = [e["summary"] for e in response.json()["events"]]
        assert summaries == ["newer", "older"]

    async def test_other_users_events_invisible(self, fake_repo, recorder):
        fake_repo.seed_profile(OTHER_USER_ID)
        other_child = fake_repo.seed_child(user_id=OTHER_USER_ID)
        fake_repo.seed_event(
            child_id=other_child.id, user_id=OTHER_USER_ID, summary="not yours"
        )
        app = build_app(fake_repo, recorder)

        async with _client(app) as client:
            response = await client.get(
                "/api/v1/events/pending", params={"child_id": str(other_child.id)}
            )
        assert response.status_code == 200
        assert response.json()["events"] == []


class TestConfirmedList:
    async def test_lists_confirmed_only_newest_first(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        fake_repo.seed_event(
            child_id=child.id, summary="older", confirmed=True,
            occurred_at=now - timedelta(hours=5),
        )
        fake_repo.seed_event(
            child_id=child.id, summary="newer", confirmed=True,
            occurred_at=now - timedelta(hours=1),
        )
        fake_repo.seed_event(child_id=child.id, summary="pending", confirmed=False)
        app = build_app(fake_repo, recorder)

        async with _client(app) as client:
            response = await client.get(
                "/api/v1/events", params={"child_id": str(child.id)}
            )
        assert response.status_code == 200
        assert [e["summary"] for e in response.json()["events"]] == ["newer", "older"]


class TestConfirm:
    async def test_confirm_single(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        event = fake_repo.seed_event(child_id=child.id, confirmed=False)
        app = build_app(fake_repo, recorder)

        async with _client(app) as client:
            response = await client.post(f"/api/v1/events/{event.id}/confirm")
        assert response.status_code == 200
        assert response.json()["event"]["confirmed"] is True
        assert fake_repo.events[str(event.id)].confirmed is True

    async def test_confirm_unknown_404(self, fake_repo, recorder):
        app = build_app(fake_repo, recorder)
        async with _client(app) as client:
            response = await client.post(f"/api/v1/events/{uuid.uuid4()}/confirm")
        assert response.status_code == 404

    async def test_confirm_batch_skips_foreign_events(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        mine = fake_repo.seed_event(child_id=child.id, confirmed=False)
        fake_repo.seed_profile(OTHER_USER_ID)
        other_child = fake_repo.seed_child(user_id=OTHER_USER_ID)
        theirs = fake_repo.seed_event(
            child_id=other_child.id, user_id=OTHER_USER_ID, confirmed=False
        )
        app = build_app(fake_repo, recorder)

        async with _client(app) as client:
            response = await client.post(
                "/api/v1/events/confirm-batch",
                json={"event_ids": [str(mine.id), str(theirs.id)]},
            )
        assert response.status_code == 200
        assert response.json()["confirmed"] == 1
        assert fake_repo.events[str(mine.id)].confirmed is True
        assert fake_repo.events[str(theirs.id)].confirmed is False


class TestDismiss:
    async def test_dismiss_unconfirmed(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        event = fake_repo.seed_event(child_id=child.id, confirmed=False)
        app = build_app(fake_repo, recorder)

        async with _client(app) as client:
            response = await client.delete(f"/api/v1/events/{event.id}")
        assert response.status_code == 204
        assert str(event.id) not in fake_repo.events

    async def test_confirmed_events_cannot_be_dismissed(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        event = fake_repo.seed_event(child_id=child.id, confirmed=True)
        app = build_app(fake_repo, recorder)

        async with _client(app) as client:
            response = await client.delete(f"/api/v1/events/{event.id}")
        assert response.status_code == 400
        assert str(event.id) in fake_repo.events
