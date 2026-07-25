"""FastAPI dependencies. Every seam here is override-friendly for offline tests."""

import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat_service import ChatService
from app.core.auth import CurrentUser
from app.db.engine import service_session, user_scoped_session
from app.db.models import SafetyEvent
from app.db.repo import Repo
from app.services.safety.classifier import SafetyClassifier
from app.services.supabase_admin import SupabaseAdmin

logger = logging.getLogger(__name__)

RepoFactory = Callable[[], AbstractAsyncContextManager[Repo]]
UserRepoFactory = Callable[[str], RepoFactory]


async def get_db(user: CurrentUser) -> AsyncIterator[AsyncSession]:
    async with user_scoped_session(user.user_id) as session:
        yield session


async def get_repo(session: Annotated[AsyncSession, Depends(get_db)]) -> Repo:
    return Repo(session)


def _repo_factory_for(user_id: str) -> RepoFactory:
    @asynccontextmanager
    async def factory() -> AsyncIterator[Repo]:
        async with user_scoped_session(user_id) as session:
            yield Repo(session)

    return factory


def get_repo_factory(user: CurrentUser) -> RepoFactory:
    """Factory of fresh RLS-scoped repos.

    The chat stream uses this instead of a request-scoped session so the
    user message commits before streaming starts and the assistant message can
    be persisted from a shielded finally even if the client disconnected.
    """
    return _repo_factory_for(user.user_id)


def get_user_repo_factory() -> UserRepoFactory:
    """Voice path: identity comes from the verified session token, not from
    CurrentUser, so the route resolves the user_id itself and asks for a
    factory afterwards. Same RLS-scoped sessions underneath."""
    return _repo_factory_for


class SafetyRecorder:
    """Append-only safety audit writes via the service path.

    safety_events has no INSERT policy for the authenticated role by design;
    these inserts intentionally skip SET ROLE. Recording failures are logged
    and never break the chat — the escalation itself already went to the
    client through the SSE stream.
    """

    async def record(
        self,
        *,
        user_id: str,
        conversation_id: uuid.UUID | str,
        source: str,
        triage_level: str,
        message_id: uuid.UUID | str | None = None,
        matched_rules: list[str] | None = None,
        classifier_output: dict[str, Any] | None = None,
        child_age_days: int | None = None,
    ) -> None:
        try:
            async with service_session() as session:
                session.add(
                    SafetyEvent(
                        user_id=uuid.UUID(str(user_id)),
                        conversation_id=uuid.UUID(str(conversation_id)),
                        message_id=uuid.UUID(str(message_id)) if message_id else None,
                        source=source,
                        triage_level=triage_level,
                        matched_rules=matched_rules,
                        classifier_output=classifier_output,
                        child_age_days=child_age_days,
                    )
                )
        except Exception:
            logger.exception("failed to record safety event (source=%s)", source)


def get_safety_recorder(request: Request) -> SafetyRecorder:
    return request.app.state.safety_recorder


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_classifier(request: Request) -> SafetyClassifier:
    return request.app.state.classifier


def get_supabase_admin(request: Request) -> SupabaseAdmin:
    return request.app.state.supabase_admin
