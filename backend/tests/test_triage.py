"""Leading-tag stream parser + severity merge."""

from app.ai.triage import (
    TAG_BUFFER_CAP,
    TriageLevel,
    TriageTagParser,
    merge_levels,
    parse_level,
)


class TestTagParsing:
    def test_whole_tag_single_chunk(self):
        parser = TriageTagParser()
        out = parser.feed('<triage level="emergency" reason="breathing"/>Call 911 now.')
        assert out == "Call 911 now."
        assert parser.done and not parser.malformed
        assert parser.level is TriageLevel.EMERGENCY
        assert parser.reason == "breathing"

    def test_tag_split_across_chunks(self):
        parser = TriageTagParser()
        assert parser.feed("<tri") == ""
        assert parser.feed('age level="none" rea') == ""
        assert parser.feed('son="general"/>Hi there') == "Hi there"
        assert parser.level is TriageLevel.NONE
        assert parser.reason == "general"
        assert not parser.malformed

    def test_leading_whitespace_tolerated(self):
        parser = TriageTagParser()
        out = parser.feed('  \n<triage level="see_doctor" reason="general"/>Text')
        assert out == "Text"
        assert parser.level is TriageLevel.SEE_DOCTOR

    def test_newline_after_tag_stripped(self):
        parser = TriageTagParser()
        out = parser.feed('<triage level="none" reason="general"/>\nFirst, put her down.')
        assert out == "First, put her down."

    def test_passthrough_after_done(self):
        parser = TriageTagParser()
        parser.feed('<triage level="none" reason="general"/>a')
        assert parser.feed("bc") == "bc"


class TestMalformed:
    def test_missing_tag_emits_content_immediately(self):
        parser = TriageTagParser()
        out = parser.feed("Put her down in the crib and take a breath.")
        assert out == "Put her down in the crib and take a breath."
        assert parser.malformed
        assert parser.level is None

    def test_unknown_level_is_malformed_and_stripped(self):
        parser = TriageTagParser()
        out = parser.feed('<triage level="banana" reason="general"/>Hello')
        assert out == "Hello"  # broken tag never leaks to the client/TTS
        assert parser.malformed
        assert parser.level is None

    def test_wrong_attribute_shape_is_malformed_and_stripped(self):
        parser = TriageTagParser()
        out = parser.feed("<triage lvl='none'/>Hello")
        assert parser.malformed
        assert "triage" not in out

    def test_buffer_cap_flushes(self):
        parser = TriageTagParser()
        garbage = "<triage " + "a" * (TAG_BUFFER_CAP + 20)
        out = parser.feed(garbage)
        assert parser.malformed
        assert out == garbage  # nothing found to strip; content not withheld

    def test_finalize_with_dangling_partial_tag(self):
        parser = TriageTagParser()
        assert parser.feed('<triage level="none"') == ""
        out = parser.finalize()
        assert out == ""  # a dangling partial tag has no user-visible content
        assert parser.malformed

    def test_finalize_after_success_is_empty(self):
        parser = TriageTagParser()
        parser.feed('<triage level="none" reason="general"/>hello')
        assert parser.finalize() == ""


class TestSeverityMerge:
    def test_ordering(self):
        levels = [
            TriageLevel.NONE,
            TriageLevel.SEE_DOCTOR,
            TriageLevel.URGENT,
            TriageLevel.EMERGENCY,
            TriageLevel.CRISIS,
        ]
        severities = [level.severity for level in levels]
        assert severities == sorted(severities)
        assert len(set(severities)) == len(severities)

    def test_merge_takes_max(self):
        assert merge_levels(TriageLevel.NONE, TriageLevel.SEE_DOCTOR) is TriageLevel.SEE_DOCTOR
        assert merge_levels(TriageLevel.EMERGENCY, TriageLevel.URGENT) is TriageLevel.EMERGENCY
        assert merge_levels(TriageLevel.EMERGENCY, TriageLevel.CRISIS) is TriageLevel.CRISIS

    def test_merge_ignores_none_values(self):
        assert merge_levels(None, TriageLevel.URGENT, None) is TriageLevel.URGENT
        assert merge_levels(None, None) is TriageLevel.NONE
        assert merge_levels() is TriageLevel.NONE

    def test_parse_level(self):
        assert parse_level("emergency") is TriageLevel.EMERGENCY
        assert parse_level("banana") is None
