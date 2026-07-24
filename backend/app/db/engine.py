"""Async engine and RLS-aware sessions.

Everything is lazy: importing this module never touches the database, so unit
tests run without one.

Two session paths exist on purpose:

- `user_scoped_session(user_id)` — runs `SET LOCAL ROLE authenticated` and
  injects JWT claims so Postgres row-level security applies to every backend
  query exactly as it does for direct Supabase access.
- `service_session()` — no role switch. Used ONLY for `safety_events` audit
  inserts, which the authenticated role intentionally cannot write.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def _apply_rls(session: AsyncSession, user_id: str) -> None:
    # SET LOCAL lasts for the current transaction only; the session autobegins
    # one on first execute and each context manager below is one transaction.
    claims = json.dumps({"sub": user_id, "role": "authenticated"})
    await session.execute(text("SET LOCAL ROLE authenticated"))
    await session.execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)"),
        {"claims": claims},
    )


@asynccontextmanager
async def user_scoped_session(user_id: str) -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        try:
            await _apply_rls(session, user_id)
            yield session
            if session.in_transaction():
                await session.commit()
        except BaseException:
            if session.in_transaction():
                await session.rollback()
            raise


@asynccontextmanager
async def service_session() -> AsyncIterator[AsyncSession]:
    """Service path (no SET ROLE). Only for safety_events audit inserts."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        except BaseException:
            if session.in_transaction():
                await session.rollback()
            raise
