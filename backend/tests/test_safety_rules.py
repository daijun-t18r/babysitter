"""Table-driven tests for the deterministic red-flag rules engine."""

import pytest

from app.ai.triage import TriageLevel
from app.services.safety.rules import POISON_CONTROL_NUMBER, evaluate_rules

AGE_8_WEEKS = 56
AGE_8_MONTHS = 243
AGE_5_MONTHS = 152

# (text, age_days, expected_level, slug expected in matched)
POSITIVE_CASES = [
    # fever, age-gated (chronological)
    ("my baby has a temp of 100.4", AGE_8_WEEKS, TriageLevel.EMERGENCY, "fever_under_3mo"),
    ("temperature is 100.6 F", 30, TriageLevel.EMERGENCY, "fever_under_3mo"),
    ("her fever is 38.1 C", 60, TriageLevel.EMERGENCY, "fever_under_3mo"),
    ("thermometer says 38°C", 89, TriageLevel.EMERGENCY, "fever_under_3mo"),
    # high fever at any age
    ("fever of 104.2", AGE_8_MONTHS, TriageLevel.EMERGENCY, "fever_high"),
    ("temp reading 40.1 C tonight", AGE_5_MONTHS, TriageLevel.EMERGENCY, "fever_high"),
    ("104 fever won't come down", AGE_8_MONTHS, TriageLevel.EMERGENCY, "fever_high"),
    # unmeasured fever in a <3mo → urgent
    ("I think she has a fever, feels really hot", AGE_8_WEEKS, TriageLevel.URGENT, "fever_under_3mo"),
    # breathing
    ("he is grunting with every breath", AGE_8_WEEKS, TriageLevel.EMERGENCY, "breathing"),
    ("her nostrils are flaring and ribs pulling in", 100, TriageLevel.EMERGENCY, "breathing"),
    ("there are pauses in his breathing", 40, TriageLevel.EMERGENCY, "breathing"),
    ("she stopped breathing for a few seconds", 40, TriageLevel.EMERGENCY, "breathing"),
    ("he's really struggling to breathe", AGE_8_MONTHS, TriageLevel.EMERGENCY, "breathing"),
    ("she's gasping", AGE_5_MONTHS, TriageLevel.EMERGENCY, "breathing"),
    # blue/gray skin
    ("his lips are turning blue", AGE_8_WEEKS, TriageLevel.EMERGENCY, "blue_skin"),
    ("her skin looks gray", AGE_8_WEEKS, TriageLevel.EMERGENCY, "blue_skin"),
    # unresponsive / floppy
    ("I can't wake her up", AGE_8_MONTHS, TriageLevel.EMERGENCY, "unresponsive"),
    ("he's gone all floppy and limp", AGE_8_WEEKS, TriageLevel.EMERGENCY, "unresponsive"),
    ("she's unresponsive", AGE_5_MONTHS, TriageLevel.EMERGENCY, "unresponsive"),
    # seizure
    ("I think she just had a seizure", AGE_5_MONTHS, TriageLevel.EMERGENCY, "seizure"),
    ("his eyes rolled back and he was convulsing", AGE_8_MONTHS, TriageLevel.EMERGENCY, "seizure"),
    # dehydration cluster
    ("no wet diaper in 10 hours", AGE_8_WEEKS, TriageLevel.EMERGENCY, "dehydration"),
    ("she hasn't had a wet diaper for 8 hrs", AGE_5_MONTHS, TriageLevel.EMERGENCY, "dehydration"),
    ("his soft spot looks sunken", AGE_8_WEEKS, TriageLevel.EMERGENCY, "dehydration"),
    ("she's crying but no tears come out", AGE_5_MONTHS, TriageLevel.EMERGENCY, "dehydration"),
    # bilious / projectile vomiting
    ("he just did a green vomit", AGE_8_WEEKS, TriageLevel.EMERGENCY, "vomiting_bilious"),
    ("PROJECTILE VOMITING across the room", AGE_8_WEEKS, TriageLevel.EMERGENCY, "vomiting_bilious"),
    # head injury: fall + sign
    (
        "she fell off the changing table and now she's so sleepy I can't wake her",
        AGE_5_MONTHS,
        TriageLevel.EMERGENCY,
        "head_injury",
    ),
    (
        "he hit his head and has been vomiting since",
        AGE_8_MONTHS,
        TriageLevel.EMERGENCY,
        "head_injury",
    ),
    # non-blanching rash
    ("she has purple spots on her legs", AGE_8_MONTHS, TriageLevel.EMERGENCY, "rash_nonblanching"),
    (
        "the rash doesn't fade when I press a glass on it",
        AGE_5_MONTHS,
        TriageLevel.EMERGENCY,
        "rash_nonblanching",
    ),
    # ingestion
    ("I think he swallowed one of my pills", AGE_8_MONTHS, TriageLevel.EMERGENCY, "ingestion"),
    ("she got into the cleaning supplies", AGE_8_MONTHS, TriageLevel.EMERGENCY, "ingestion"),
    ("he might have eaten a button battery", AGE_8_MONTHS, TriageLevel.EMERGENCY, "ingestion"),
    # parent crisis
    ("I'm scared I'm going to hurt the baby", AGE_8_WEEKS, TriageLevel.CRISIS, "parent_crisis"),
    ("I want to hurt myself", AGE_8_WEEKS, TriageLevel.CRISIS, "parent_crisis"),
    ("I'm afraid I might shake the baby", AGE_8_WEEKS, TriageLevel.CRISIS, "parent_crisis"),
    ("I can't take it anymore", AGE_8_WEEKS, TriageLevel.CRISIS, "parent_overwhelm"),
    ("I'm about to lose it", AGE_8_WEEKS, TriageLevel.CRISIS, "parent_overwhelm"),
]


@pytest.mark.parametrize("text,age_days,expected_level,expected_slug", POSITIVE_CASES)
def test_rule_fires(text: str, age_days: int, expected_level: TriageLevel, expected_slug: str):
    result = evaluate_rules(text, age_days)
    assert result.fired, f"expected a rule hit for: {text!r}"
    assert result.level is expected_level
    assert expected_slug in result.matched


# Negative lookalikes: must NOT fire and must NOT weak-hit.
NEGATIVE_CASES = [
    ("I've got such baby fever watching her sleep", AGE_8_MONTHS),
    ("her fever broke yesterday and she seems better", AGE_8_MONTHS),
    ("he was fussy but he's breathing fine now", AGE_8_WEEKS),
    ("no fever, just fussy tonight", AGE_8_WEEKS),
    ("how much should a 3 month old eat", 91),
    ("she is 104 days old today", AGE_5_MONTHS),
]


@pytest.mark.parametrize("text,age_days", NEGATIVE_CASES)
def test_lookalikes_do_not_fire(text: str, age_days: int):
    result = evaluate_rules(text, age_days)
    assert not result.fired, f"unexpected rule hit for: {text!r} → {result.matched}"
    assert not result.weak_hit, f"unexpected weak hit for: {text!r} → {result.weak_words}"


class TestFeverAgeGate:
    def test_100_4_at_8_weeks_is_emergency(self):
        result = evaluate_rules("rectal temp is 100.4", AGE_8_WEEKS)
        assert result.level is TriageLevel.EMERGENCY
        assert "fever_under_3mo" in result.matched

    def test_100_4_at_8_months_is_not_emergency(self):
        result = evaluate_rules("rectal temp is 100.4", AGE_8_MONTHS)
        assert not result.fired
        # But the fever mention is never silently passed:
        assert result.weak_hit
        assert "fever" in result.weak_words

    def test_unknown_age_treated_as_youngest(self):
        result = evaluate_rules("temp is 100.9", None)
        assert result.level is TriageLevel.EMERGENCY
        assert "fever_under_3mo" in result.matched

    def test_gate_boundary_at_90_days(self):
        assert evaluate_rules("temp 100.5", 89).level is TriageLevel.EMERGENCY
        assert not evaluate_rules("temp 100.5", 90).fired

    def test_numeric_temp_beats_reassuring_phrase(self):
        # "fever broke" suppresses the word-family, never a stated number.
        result = evaluate_rules("fever broke yesterday but tonight it's 104.5", AGE_8_MONTHS)
        assert result.level is TriageLevel.EMERGENCY
        assert "fever_high" in result.matched


class TestWeakHits:
    def test_bare_fall_is_weak_hit_not_rule(self):
        result = evaluate_rules("he fell off the bed but seems okay", AGE_5_MONTHS)
        assert not result.fired
        assert result.weak_hit
        assert "fall" in result.weak_words

    def test_vomit_mention_is_weak_hit(self):
        result = evaluate_rules("she threw up a little after her feed", AGE_5_MONTHS)
        assert not result.fired
        assert result.weak_hit

    def test_plain_question_no_weak_hit(self):
        result = evaluate_rules("how do I get her to nap longer", AGE_5_MONTHS)
        assert not result.fired
        assert not result.weak_hit


class TestIngestionNotes:
    def test_poison_control_number_included(self):
        result = evaluate_rules("he swallowed a vitamin gummy bottle's worth", AGE_8_MONTHS)
        assert "ingestion" in result.matched
        assert any(POISON_CONTROL_NUMBER in note for note in result.notes)


class TestMultipleRules:
    def test_max_severity_wins(self):
        result = evaluate_rules(
            "she has a fever of 101 and I can't take it anymore", AGE_8_WEEKS
        )
        assert result.level is TriageLevel.CRISIS
        assert "parent_overwhelm" in result.matched
        assert "fever_under_3mo" in result.matched
        assert result.reason == "parent_overwhelm"
