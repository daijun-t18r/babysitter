from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import get_repo
from app.api.serializers import serialize_child, serialize_profile
from app.core.auth import CurrentUser
from app.db.repo import Repo

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
