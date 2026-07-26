import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.deps import get_repo, get_supabase_admin
from app.api.serializers import serialize_child, serialize_profile
from app.core.auth import CurrentUser
from app.core.config import get_settings
from app.db.repo import Repo
from app.services.supabase_admin import SupabaseAdmin, SupabaseAdminError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/me")
async def get_me(user: CurrentUser, repo: Annotated[Repo, Depends(get_repo)]) -> dict[str, Any]:
    profile = await repo.get_profile(user.user_id)
    children = await repo.list_children(user.user_id)
    return {
        "user_id": user.user_id,
        "email": user.email,
        "profile": serialize_profile(profile) if profile else None,
        "children": [serialize_child(c) for c in children],
    }


@router.delete("/me", status_code=204)
async def delete_me(
    user: CurrentUser,
    admin: Annotated[SupabaseAdmin, Depends(get_supabase_admin)],
) -> Response:
    """GDPR account deletion (launch gate 4a).

    Deletes the Supabase auth user; the auth.users → profiles ON DELETE
    CASCADE chain erases all app data atomically. The backend performs NO
    app-side deletes: on admin failure nothing is deleted (502), so a partial
    delete can never orphan the auth user. Identity comes only from the
    verified token — deleting another user is structurally impossible.
    """
    settings = get_settings()
    if not settings.supabase_service_role_key:
        raise HTTPException(503, detail="Account deletion is not configured")

    try:
        await admin.delete_user(user.user_id)
    except SupabaseAdminError:
        logger.exception("account deletion failed (user_id=%s); nothing deleted", user.user_id)
        raise HTTPException(
            502, detail="Account deletion failed upstream; nothing was deleted"
        ) from None
    return Response(status_code=204)
