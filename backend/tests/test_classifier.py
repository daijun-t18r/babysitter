"""SafetyClassifier: JSON-only parsing, 2s timeout, silent degradation."""

from app.ai.triage import TriageLevel
from app.services.safety.classifier import SafetyClassifier
from tests.conftest import FakeClassifierClient


class TestClassifier:
    async def test_valid_json_parsed(self):
        client = FakeClassifierClient({"triage": "emergency", "reasons": ["breathing"]})
        classifier = SafetyClassifier(client=client, model="test-haiku")
        result = await classifier.classify("he's grunting", 56)
        assert result is not None
        assert result.level is TriageLevel.EMERGENCY
        assert result.reasons == ("breathing",)
        assert result.raw["triage"] == "emergency"

    async def test_fenced_json_tolerated(self):
        client = FakeClassifierClient('```json\n{"triage": "none", "reasons": []}\n```')
        classifier = SafetyClassifier(client=client, model="test-haiku")
        result = await classifier.classify("nap question", 100)
        assert result is not None
        assert result.level is TriageLevel.NONE

    async def test_invalid_json_degrades_to_none(self):
        client = FakeClassifierClient("I think this is an emergency because...")
        classifier = SafetyClassifier(client=client, model="test-haiku")
        assert await classifier.classify("anything", 56) is None

    async def test_unknown_level_degrades_to_none(self):
        client = FakeClassifierClient({"triage": "catastrophic", "reasons": []})
        classifier = SafetyClassifier(client=client, model="test-haiku")
        assert await classifier.classify("anything", 56) is None

    async def test_upstream_error_degrades_to_none(self):
        client = FakeClassifierClient({}, raises=True)
        classifier = SafetyClassifier(client=client, model="test-haiku")
        assert await classifier.classify("anything", 56) is None

    async def test_timeout_degrades_to_none(self):
        client = FakeClassifierClient({"triage": "none", "reasons": []}, delay_s=0.2)
        classifier = SafetyClassifier(client=client, model="test-haiku", timeout_s=0.05)
        assert await classifier.classify("anything", 56) is None
