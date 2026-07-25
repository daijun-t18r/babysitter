"""Migration chain integrity + offline SQL assertions (no database needed).

Mirrors the tests/alembic convention used across our other backends: the
revision graph must have a single head, and `upgrade head --sql` must emit
the schema invariants the audit fixed (initplan RLS form, audit-trail FK
behavior, FK index coverage).
"""

import io
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[2]


def make_config(buffer: io.StringIO | None = None) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"), stdout=buffer or io.StringIO())
    # Offline `--sql` DDL is written to output_buffer, not the message stdout.
    config.output_buffer = buffer or io.StringIO()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


@pytest.fixture(scope="module")
def offline_sql() -> str:
    buffer = io.StringIO()
    command.upgrade(make_config(buffer), "head", sql=True)
    return buffer.getvalue()


class TestRevisionChain:
    def test_single_head_named_001(self):
        script = ScriptDirectory.from_config(make_config())
        heads = script.get_heads()
        assert heads == ["001"]

    def test_chain_walks_to_base(self):
        script = ScriptDirectory.from_config(make_config())
        revisions = list(script.walk_revisions("base", "heads"))
        assert [r.revision for r in revisions] == ["001"]


class TestOfflineSql:
    def test_all_tables_created(self, offline_sql):
        for table in (
            "profiles",
            "children",
            "conversations",
            "messages",
            "events",
            "safety_events",
        ):
            assert f"create table public.{table}" in offline_sql

    def test_rls_enabled_on_every_table(self, offline_sql):
        assert offline_sql.count("enable row level security") == 6

    def test_policies_use_initplan_auth_uid_form(self, offline_sql):
        # Supabase perf guidance: always (select auth.uid()), never bare auth.uid().
        assert "(select auth.uid())" in offline_sql
        for line in offline_sql.splitlines():
            if "auth.uid()" in line:
                assert "(select auth.uid())" in line, f"bare auth.uid() in: {line.strip()}"

    def test_safety_events_survive_conversation_deletion(self, offline_sql):
        start = offline_sql.index("create table public.safety_events")
        block = offline_sql[start : offline_sql.index(";", start)]
        assert "references public.conversations(id) on delete set null" in block
        assert "on delete cascade" not in block.replace(
            "references public.profiles(id) on delete cascade", ""
        )

    def test_fk_index_coverage(self, offline_sql):
        for index in (
            "children_user_idx",
            "conversations_user_recent_idx",
            "conversations_child_idx",
            "messages_conversation_idx",
            "events_child_time_idx",
            "events_pending_confirm_idx",
            "events_user_idx",
            "events_message_idx",
            "safety_events_user_idx",
            "safety_events_conversation_idx",
            "safety_events_message_idx",
        ):
            assert f"create index {index}" in offline_sql

    def test_safety_events_has_no_write_policies(self, offline_sql):
        start = offline_sql.index("create table public.safety_events")
        tail = offline_sql[start:]
        assert 'create policy "read own safety events"' in tail
        assert tail.count("create policy") == 1

    def test_signup_trigger_present(self, offline_sql):
        assert "create trigger on_auth_user_created" in offline_sql
        assert "security definer set search_path = public" in offline_sql
