"""DELETE /api/v1/me — GDPR account deletion (launch gate 4a).

The route deletes ONLY the Supabase auth user; app data erasure rides the
auth.users → profiles ON DELETE CASCADE chain. These tests pin the atomicity
contract: the backend never performs an app-side delete, so an admin failure
leaves everything (including the auth user) fully intact.
"""

import httpx
import pytest

from app.core.config import get_settings
from app.services.supabase_admin import SupabaseAdmin, SupabaseAdminError
from tests.conftest import TEST_USER_ID, FakeSupabaseAdmin, build_app

SERVICE_ROLE_KEY = "test-service-role-key"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def service_role_key(monkeypatch):
    """Configure the service-role key on the cached Settings instance."""
    monkeypatch.setattr(get_settings(), "supabase_service_role_key", SERVICE_ROLE_KEY)
    return SERVICE_ROLE_KEY


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _snapshot(fake_repo):
    return (
        dict(fake_repo.profiles),
        dict(fake_repo.children),
        dict(fake_repo.conversations),
        list(fake_repo.messages),
        dict(fake_repo.events),
    )


class TestDeleteMeRoute:
    async def test_deletes_auth_user_only_204(self, fake_repo, recorder, service_role_key):
        child = fake_repo.seed_child()
        fake_repo.seed_conversation(child_id=child.id)
        admin = FakeSupabaseAdmin()
        app = build_app(fake_repo, recorder, supabase_admin=admin)
        before = _snapshot(fake_repo)
        async with _client(app) as client:
            response = await client.delete("/api/v1/me")
        assert response.status_code == 204
        assert admin.deleted == [TEST_USER_ID]
        # No app-side deletes: erasure is the auth.users → profiles cascade.
        assert _snapshot(fake_repo) == before

    async def test_admin_failure_502_nothing_deleted(
        self, fake_repo, recorder, service_role_key
    ):
        fake_repo.seed_child()
        admin = FakeSupabaseAdmin(raises=True)
        app = build_app(fake_repo, recorder, supabase_admin=admin)
        before = _snapshot(fake_repo)
        async with _client(app) as client:
            response = await client.delete("/api/v1/me")
        assert response.status_code == 502
        assert admin.deleted == []
        assert _snapshot(fake_repo) == before

    async def test_unset_service_role_key_503(self, fake_repo, recorder, monkeypatch):
        monkeypatch.setattr(get_settings(), "supabase_service_role_key", "")
        admin = FakeSupabaseAdmin()
        app = build_app(fake_repo, recorder, supabase_admin=admin)
        async with _client(app) as client:
            response = await client.delete("/api/v1/me")
        assert response.status_code == 503
        assert admin.deleted == []

    async def test_identity_comes_from_auth_seam_only(
        self, fake_repo, recorder, service_role_key
    ):
        """A hostile body/query naming another user changes nothing: the route
        takes no user parameter — identity is the verified token's sub."""
        admin = FakeSupabaseAdmin()
        app = build_app(fake_repo, recorder, supabase_admin=admin)
        async with _client(app) as client:
            response = await client.request(
                "DELETE",
                f"/api/v1/me?user_id={OTHER_USER_ID}",
                json={"user_id": OTHER_USER_ID},
            )
        assert response.status_code == 204
        assert admin.deleted == [TEST_USER_ID]


class TestSupabaseAdminClient:
    """Unit tests for the real client against an httpx MockTransport."""

    def _admin(self, handler) -> SupabaseAdmin:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return SupabaseAdmin(client=client)

    async def test_calls_admin_endpoint_with_service_role_key(self, service_role_key):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={})

        await self._admin(handler).delete_user(TEST_USER_ID)
        assert len(seen) == 1
        request = seen[0]
        assert request.method == "DELETE"
        supabase_url = get_settings().supabase_url.rstrip("/")
        assert str(request.url) == f"{supabase_url}/auth/v1/admin/users/{TEST_USER_ID}"
        assert request.headers["Authorization"] == f"Bearer {SERVICE_ROLE_KEY}"
        assert request.headers["apikey"] == SERVICE_ROLE_KEY

    async def test_non_2xx_raises(self, service_role_key):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"msg": "boom"})

        with pytest.raises(SupabaseAdminError, match="500"):
            await self._admin(handler).delete_user(TEST_USER_ID)

    async def test_transport_error_raises(self, service_role_key):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("connect timeout")

        with pytest.raises(SupabaseAdminError):
            await self._admin(handler).delete_user(TEST_USER_ID)
