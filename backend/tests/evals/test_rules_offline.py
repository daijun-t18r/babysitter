"""Offline half of the golden safety suite. Always runs in CI — no network.

Every case's user messages go through the REAL deterministic rules engine
(evaluate_rules) plus the weak-hit floor the chat pipeline applies. Asserts:

1. Consistency: the deterministic floor never exceeds the case's expected
   maximum level (otherwise the live expectation could never hold — the final
   level is max(rules, classifier, model)).
2. Recall: cases marked `rules_fire: true` must fire at exactly the expected
   level, with the expected reason slug in the matched set. This is the
   deterministic layer of the red-flag recall launch gate.
3. Precision: cases marked (or defaulted) `rules_fire: false` must not fire at
   all — near-misses must not over-escalate deterministically.
4. Suite integrity: category minimums, unique ids, age-band pair direction,
   crisis cases always carry a hotline expectation.
"""

from collections import Counter, defaultdict

import pytest

from app.ai.triage import TriageLevel, TriageTagParser
from app.services.safety.rules import RuleResult, evaluate_rules
from tests.evals.loader import (
    MIN_COUNTS,
    TOTAL_RANGE,
    GoldenCase,
    load_cases,
)

CASES = load_cases()
CASE_IDS = [case.id for case in CASES]

CRISIS_HOTLINE_MARKERS = ("988", "741741", "852-6262")


def _message_floor(result: RuleResult) -> TriageLevel:
    """The deterministic floor the chat pipeline enforces for one message."""
    if result.fired:
        return result.level
    if result.weak_hit:
        return TriageLevel.SEE_DOCTOR
    return TriageLevel.NONE


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_rules_engine_and_floor(case: GoldenCase):
    age_days = case.birth_date_offset_days
    results = [evaluate_rules(message, age_days) for message in case.messages]

    floor = max((_message_floor(r) for r in results), key=lambda level: level.severity)
    expected_max = case.expected_max_level
    assert floor.severity <= expected_max.severity, (
        f"{case.id}: deterministic floor {floor.value} exceeds expected max "
        f"{expected_max.value} — rules would over-escalate past the case's allowance"
    )

    fired = [r for r in results if r.fired]
    if case.rules_fire:
        assert fired, f"{case.id}: rules engine did not fire (deterministic recall gap)"
        top = max((r.level for r in fired), key=lambda level: level.severity)
        assert top is expected_max, (
            f"{case.id}: rules fired at {top.value}, expected {expected_max.value}"
        )
        if case.reasons:
            matched = {slug for r in fired for slug in r.matched}
            assert matched & set(case.reasons), (
                f"{case.id}: expected reason in {case.reasons}, rules matched {sorted(matched)}"
            )
    else:
        assert not fired, (
            f"{case.id}: rules engine fired unexpectedly on "
            f"{[r.matched for r in fired]} (deterministic over-escalation)"
        )


def test_category_minimums_and_total():
    counts = Counter(case.category for case in CASES)
    for category, minimum in MIN_COUNTS.items():
        assert counts[category] >= minimum, (
            f"category {category}: {counts[category]} cases, minimum is {minimum}"
        )
    total = len(CASES)
    assert TOTAL_RANGE[0] <= total <= TOTAL_RANGE[1], f"total case count {total}"


def test_case_ids_unique():
    # load_cases() raises on duplicates; this pins the guarantee as a test.
    assert len(CASE_IDS) == len(set(CASE_IDS))


def test_age_band_pairs_directional():
    pairs: dict[str, dict[str, GoldenCase]] = defaultdict(dict)
    for case in CASES:
        if case.category != "age_band_pairs":
            continue
        prefix, _, suffix = case.id.rpartition("_")
        assert suffix in ("young", "old"), f"{case.id}: pair ids must end in _young/_old"
        pairs[prefix][suffix] = case

    assert pairs, "no age_band_pairs found"
    for prefix, members in pairs.items():
        assert set(members) == {"young", "old"}, f"incomplete pair: {prefix}"
        young, old = members["young"], members["old"]
        assert young.birth_date_offset_days < old.birth_date_offset_days, (
            f"{prefix}: _young must be the younger profile"
        )
        # Direction: caution never increases with age for the same question.
        assert (
            young.expected_max_level.severity >= old.expected_max_level.severity
        ), f"{prefix}: younger band must be at least as cautious"
        # The pair must actually assert a difference (level or content).
        differs = (
            set(young.levels) != set(old.levels)
            or young.include_groups != old.include_groups
            or [p.pattern for p in young.not_match] != [p.pattern for p in old.not_match]
        )
        assert differs, f"{prefix}: pair asserts no directional difference"


def test_crisis_cases_require_hotline():
    for case in CASES:
        if case.category != "crisis":
            continue
        flat = [s for group in case.include_groups for s in group]
        assert any(marker in s for s in flat for marker in CRISIS_HOTLINE_MARKERS), (
            f"{case.id}: crisis case must assert a hotline number in must_include_any"
        )


def test_ingestion_case_requires_poison_control():
    ingestion = [
        case
        for case in CASES
        if case.reasons and "ingestion" in case.reasons
    ]
    assert ingestion, "suite must include an ingestion red-flag case"
    for case in ingestion:
        flat = [s for group in case.include_groups for s in group]
        assert any("222-1222" in s for s in flat), (
            f"{case.id}: ingestion case must assert the Poison Control number"
        )


@pytest.mark.parametrize("level", list(TriageLevel), ids=[level.value for level in TriageLevel])
def test_every_level_round_trips_through_real_parser(level: TriageLevel):
    """Every level the suite can expect must survive the real streaming parser."""
    parser = TriageTagParser()
    visible = parser.feed(f'<triage level="{level.value}" reason="general"/>Hello there.')
    visible += parser.finalize()
    assert parser.done and not parser.malformed
    assert parser.level is level
    assert visible == "Hello there."
