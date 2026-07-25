"""Add safety_events to the supabase_realtime publication.

The voice path delivers triage cards out-of-band: /v1/chat/completions writes
safety_events rows and the PWA subscribes via Supabase Realtime (RLS applies —
users only receive their own rows via the existing select policy). Guarded so
the migration is a no-op on databases without the supabase_realtime
publication (plain Postgres in CI) and idempotent when re-run.

Revision ID: 002
Revises: 001
Create Date: 2026-07-24

"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (
       select 1 from pg_publication_tables
       where pubname = 'supabase_realtime'
         and schemaname = 'public'
         and tablename = 'safety_events'
     ) then
    alter publication supabase_realtime add table public.safety_events;
  end if;
end
$$;
"""

DOWNGRADE_SQL = """
do $$
begin
  if exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'safety_events'
  ) then
    alter publication supabase_realtime drop table public.safety_events;
  end if;
end
$$;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
