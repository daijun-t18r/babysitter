"""Initial schema: profiles, children, conversations, messages, events, safety_events.

Consolidates the original supabase/migrations SQL with three structure-audit
fixes baked in (applied pre-first-commit, so no follow-up migration needed):
1. RLS policies use `(select auth.uid())` — the initplan form Supabase's
   performance guidance requires (bare auth.uid() re-evaluates per row).
2. safety_events.conversation_id is nullable ON DELETE SET NULL: the audit
   trail survives conversation deletion. Account deletion (user_id CASCADE)
   still removes everything — that path IS the GDPR erasure mechanism.
3. Missing FK indexes added: conversations(child_id), events(user_id),
   events(message_id), safety_events(conversation_id), safety_events(message_id).

Revision ID: 001
Revises:
Create Date: 2026-07-24

"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE_SQL = """
-- profiles: 1:1 with auth.users, auto-created by trigger -----------------------
create table public.profiles (
  id                      uuid primary key references auth.users(id) on delete cascade,
  display_name            text,
  phone                   text,                     -- for future PSTN caller-id mapping
  disclaimer_accepted_at  timestamptz,              -- consent audit (one-tap onboarding card)
  created_at              timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "own profile" on public.profiles
  for all using ((select auth.uid()) = id) with check ((select auth.uid()) = id);

-- auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data ->> 'full_name', null))
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- children (not "babies"): child-centric timeline supports the long-term vision (P7)
create table public.children (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references public.profiles(id) on delete cascade,
  name               text not null default 'Baby',
  birth_date         date not null check (birth_date <= current_date),
  due_date           date,                          -- set if born 3+ weeks early -> corrected age
  feeding_type       text check (feeding_type in ('breast','formula','mixed','solids')),
  notes              text,                          -- parent-entered, unverified (prompt marks it as such)
  pediatrician_name  text,
  pediatrician_phone text,                          -- powers the escalation card tap-to-call
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index children_user_idx on public.children (user_id);

alter table public.children enable row level security;

create policy "own children" on public.children
  for all using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- conversations + messages -----------------------------------------------------
-- triage levels used across tables:
--   none | see_doctor | urgent | emergency | crisis
create table public.conversations (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references public.profiles(id) on delete cascade,
  child_id        uuid references public.children(id) on delete set null,
  title           text,
  max_triage      text not null default 'none'
                    check (max_triage in ('none','see_doctor','urgent','emergency','crisis')),
  created_at      timestamptz not null default now(),
  last_message_at timestamptz not null default now()
);

create index conversations_user_recent_idx on public.conversations (user_id, last_message_at desc);
create index conversations_child_idx on public.conversations (child_id);

create table public.messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  role            text not null check (role in ('user','assistant')),
  content         text not null,
  input_mode      text not null default 'text' check (input_mode in ('text','voice')),
  triage_level    text not null default 'none'
                    check (triage_level in ('none','see_doctor','urgent','emergency','crisis')),
  triage_reason   text,
  degraded_safety boolean not null default false,   -- rules no-match + classifier failed -> human review queue
  model           text,
  input_tokens    int,
  output_tokens   int,
  created_at      timestamptz not null default now()
);

create index messages_conversation_idx on public.messages (conversation_id, created_at);

alter table public.conversations enable row level security;
alter table public.messages enable row level security;

create policy "own conversations" on public.conversations
  for all using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

create policy "own messages" on public.messages
  for all using (exists (select 1 from public.conversations c
                         where c.id = conversation_id and c.user_id = (select auth.uid())))
  with check   (exists (select 1 from public.conversations c
                         where c.id = conversation_id and c.user_id = (select auth.uid())));

-- events: child-centric timeline (P3: records are a byproduct of chat) ---------
-- unconfirmed events are NEVER injected into prompts
create table public.events (
  id          uuid primary key default gen_random_uuid(),
  child_id    uuid not null references public.children(id) on delete cascade,
  user_id     uuid not null references public.profiles(id) on delete cascade,
  kind        text not null check (kind in ('feeding','sleep','diaper','symptom','medication','note')),
  summary     text not null,                        -- "breastfed ~15 min", "temp felt warm"
  occurred_at timestamptz not null,
  source      text not null default 'chat_extraction'
                check (source in ('chat_extraction','manual')),
  confirmed   boolean not null default false,       -- text mode: inline confirm; call mode: post-call batch confirm
  message_id  uuid references public.messages(id) on delete set null,
  metadata    jsonb not null default '{}',
  created_at  timestamptz not null default now()
);

create index events_child_time_idx on public.events (child_id, occurred_at desc);
create index events_pending_confirm_idx on public.events (user_id, created_at desc) where not confirmed;
create index events_user_idx on public.events (user_id);
create index events_message_idx on public.events (message_id);

alter table public.events enable row level security;

create policy "own events" on public.events
  for all using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- safety_events: append-only safety audit trail --------------------------------
-- users may READ their own; user-scoped sessions can never write/update/delete
-- (inserts happen from the backend service path with role reset, outside SET ROLE authenticated).
-- conversation_id is SET NULL on delete so deleting a conversation cannot destroy
-- audit rows; deleting the ACCOUNT (user_id cascade) removes everything, which is
-- the intended GDPR erasure path.
create table public.safety_events (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references public.profiles(id) on delete cascade,
  conversation_id   uuid references public.conversations(id) on delete set null,
  message_id        uuid references public.messages(id) on delete set null,
  source            text not null check (source in ('rules','classifier','model_tag','output_filter','manual_review')),
  triage_level      text not null
                      check (triage_level in ('none','see_doctor','urgent','emergency','crisis')),
  matched_rules     text[],                         -- e.g. {'fever_under_3mo','breathing'}
  classifier_output jsonb,                          -- raw classifier JSON for audit
  child_age_days    int,                            -- age at time of event
  created_at        timestamptz not null default now()
);

create index safety_events_user_idx on public.safety_events (user_id, created_at desc);
create index safety_events_conversation_idx on public.safety_events (conversation_id);
create index safety_events_message_idx on public.safety_events (message_id);

alter table public.safety_events enable row level security;

create policy "read own safety events" on public.safety_events
  for select using ((select auth.uid()) = user_id);
-- intentionally no insert/update/delete policies for authenticated
"""

DOWNGRADE_SQL = """
drop table if exists public.safety_events;
drop table if exists public.events;
drop table if exists public.messages;
drop table if exists public.conversations;
drop table if exists public.children;
drop trigger if exists on_auth_user_created on auth.users;
drop function if exists public.handle_new_user();
drop table if exists public.profiles;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
