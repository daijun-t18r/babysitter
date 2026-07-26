"""Supabase Auth Admin API client (GDPR account deletion, launch gate 4a).

Deleting the auth user is the ONLY delete the backend performs: the
`profiles.id → auth.users(id) ON DELETE CASCADE` chain then erases every app
row (profile, children, conversations, messages, events, safety_events)
atomically inside Postgres. Any admin-call failure raises so the route can
answer 502 with NOTHING deleted — a partial app-side delete could orphan the
auth user, so none is ever attempted. The client is injectable for tests.
"""

from typing import Any

from app.core.config import get_settings

ADMIN_TIMEOUT_S = 5.0


class SupabaseAdminError(Exception):
    """The admin API call failed; nothing was deleted."""


class SupabaseAdmin:
    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=ADMIN_TIMEOUT_S)
        return self._client

    async def delete_user(self, user_id: str) -> None:
        settings = get_settings()
        url = f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{user_id}"
        headers = {
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "apikey": settings.supabase_service_role_key,
        }
        try:
            response = await self._get_client().delete(url, headers=headers)
        except Exception as exc:
            raise SupabaseAdminError(f"admin delete failed: {exc}") from exc
        if not response.is_success:
            raise SupabaseAdminError(f"admin delete returned {response.status_code}")
