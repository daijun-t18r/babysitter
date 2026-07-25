import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.ai.prompt_builder import utc_today
from app.api.deps import get_repo
from app.api.serializers import serialize_child
from app.core.auth import CurrentUser
from app.db.repo import Repo

router = APIRouter()

FeedingType = Literal["breast", "formula", "mixed", "solids"]


class ChildCreate(BaseModel):
    name: str = Field(default="Baby", min_length=1, max_length=100)
    birth_date: date
    due_date: date | None = None
    feeding_type: FeedingType | None = None
    notes: str | None = Field(default=None, max_length=4000)
    pediatrician_name: str | None = Field(default=None, max_length=200)
    pediatrician_phone: str | None = Field(default=None, max_length=50)

    @field_validator("birth_date")
    @classmethod
    def birth_date_not_in_future(cls, v: date) -> date:
        if v > utc_today():
            raise ValueError("birth_date cannot be in the future")
        return v


class ChildUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    birth_date: date | None = None
    due_date: date | None = None
    feeding_type: FeedingType | None = None
    notes: str | None = Field(default=None, max_length=4000)
    pediatrician_name: str | None = Field(default=None, max_length=200)
    pediatrician_phone: str | None = Field(default=None, max_length=50)

    @field_validator("birth_date")
    @classmethod
    def birth_date_not_in_future(cls, v: date | None) -> date | None:
        if v is not None and v > utc_today():
            raise ValueError("birth_date cannot be in the future")
        return v


@router.post("/children", status_code=201)
async def create_child(
    body: ChildCreate, user: CurrentUser, repo: Annotated[Repo, Depends(get_repo)]
) -> dict[str, Any]:
    child = await repo.create_child(user.user_id, **body.model_dump())
    return serialize_child(child)


@router.patch("/children/{child_id}")
async def update_child(
    child_id: uuid.UUID,
    body: ChildUpdate,
    user: CurrentUser,
    repo: Annotated[Repo, Depends(get_repo)],
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    child = await repo.update_child(child_id, user.user_id, **fields)
    if child is None:
        raise HTTPException(404, detail="Child not found")
    return serialize_child(child)
