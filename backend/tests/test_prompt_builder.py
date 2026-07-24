"""Age math and prompt block assembly."""

from datetime import date, timedelta

from app.ai.prompt_builder import (
    build_child_context,
    build_system_blocks,
    compute_child_age,
    load_static_blocks,
)

TODAY = date(2026, 7, 23)


class TestAgeMath:
    def test_born_yesterday(self):
        age = compute_child_age(TODAY - timedelta(days=1), today=TODAY)
        assert age.days == 1
        assert age.weeks == 0
        assert age.rem_days == 1
        assert age.band == "0-3m"
        assert not age.conservative_applied

    def test_exactly_12_weeks(self):
        age = compute_child_age(TODAY - timedelta(weeks=12), today=TODAY)
        assert age.days == 84
        assert age.weeks == 12
        assert age.rem_days == 0
        assert age.band == "0-3m"

    def test_boundary_plus_3_days_uses_younger_band(self):
        # 94 days: raw band 3-6m, but within one week of the boundary → 0-3m cautions.
        age = compute_child_age(TODAY - timedelta(days=94), today=TODAY)
        assert age.raw_band == "3-6m"
        assert age.band == "0-3m"
        assert age.conservative_applied

    def test_boundary_plus_8_days_uses_own_band(self):
        age = compute_child_age(TODAY - timedelta(days=98), today=TODAY)
        assert age.band == "3-6m"
        assert not age.conservative_applied

    def test_six_month_boundary_conservative(self):
        age = compute_child_age(TODAY - timedelta(days=185), today=TODAY)
        assert age.raw_band == "6-12m"
        assert age.band == "3-6m"
        assert age.conservative_applied

    def test_twelve_month_boundary_conservative(self):
        age = compute_child_age(TODAY - timedelta(days=368), today=TODAY)
        assert age.raw_band == "12m+"
        assert age.band == "6-12m"
        assert age.conservative_applied

    def test_corrected_age_for_preterm(self):
        birth = TODAY - timedelta(days=70)
        due = birth + timedelta(days=28)  # born 4 weeks early
        age = compute_child_age(birth, due_date=due, today=TODAY)
        assert age.days == 70  # chronological unchanged
        assert age.corrected_days == 42
        assert age.corrected_weeks == 6

    def test_no_due_date_no_corrected_age(self):
        age = compute_child_age(TODAY - timedelta(days=70), today=TODAY)
        assert age.corrected_days is None

    def test_late_baby_no_corrected_age(self):
        birth = TODAY - timedelta(days=70)
        due = birth - timedelta(days=5)  # born after the due date
        age = compute_child_age(birth, due_date=due, today=TODAY)
        assert age.corrected_days is None

    def test_future_birth_date_clamped(self):
        age = compute_child_age(TODAY + timedelta(days=3), today=TODAY)
        assert age.days == 0


class TestChildContext:
    def test_includes_name_age_feeding_and_notes(self):
        ctx = build_child_context(
            name="Mia",
            birth_date=TODAY - timedelta(days=45),
            feeding_type="breast",
            notes="hates the swaddle",
            today=TODAY,
            local_hour=3,
        )
        assert "<child_context>" in ctx and "</child_context>" in ctx
        assert "Mia" in ctx
        assert "6 weeks, 3 days" in ctx
        assert "45 days, chronological" in ctx
        assert "breast" in ctx
        assert "middle of the night" in ctx
        assert "unverified" in ctx
        assert "hates the swaddle" in ctx

    def test_corrected_age_note_states_chronological_fever_rule(self):
        birth = TODAY - timedelta(days=70)
        ctx = build_child_context(
            name="Leo",
            birth_date=birth,
            due_date=birth + timedelta(days=28),
            today=TODAY,
        )
        assert "Corrected age: 6 weeks" in ctx
        assert "CHRONOLOGICAL" in ctx
        assert "fever" in ctx.lower()

    def test_conservative_band_flagged(self):
        ctx = build_child_context(
            name="Ava", birth_date=TODAY - timedelta(days=94), today=TODAY
        )
        assert "Age band: 0-3m" in ctx
        assert "younger" in ctx


class TestSystemBlocks:
    def test_cache_breakpoint_on_last_static_block(self):
        blocks = build_system_blocks("<child_context>dynamic</child_context>")
        static_count = len(load_static_blocks())
        assert len(blocks) == static_count + 1
        # cache_control only on the last static block
        for i, block in enumerate(blocks[:static_count]):
            if i == static_count - 1:
                assert block.get("cache_control") == {"type": "ephemeral"}
            else:
                assert "cache_control" not in block
        # dynamic child context strictly after the breakpoint, uncached
        assert blocks[-1]["text"] == "<child_context>dynamic</child_context>"
        assert "cache_control" not in blocks[-1]

    def test_protocol_stated_at_start_and_end_of_static_prompt(self):
        static = load_static_blocks()
        combined = "\n".join(static)
        assert combined.count('<triage level="none|see_doctor|urgent|emergency|crisis"') >= 2
        # safety block leads with the protocol; the final static block ends with it
        assert "Triage tag protocol" in static[1][:500]
        assert "triage tag protocol" in static[-1][-600:].lower()

    def test_knowledge_packs_all_compiled(self):
        combined = "\n".join(load_static_blocks())
        for marker in (
            "PURPLE crying",
            "Alone, on the Back",
            "NEVER dilute formula",
            "100.4",
            "rule of 3s",
            "benzocaine",
            "4-month regression",
            "zinc-oxide",
            "CORRECTED age",
            "1-833-852-6262",
        ):
            assert marker in combined, f"knowledge marker missing: {marker}"
