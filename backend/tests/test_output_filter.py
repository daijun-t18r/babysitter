"""Dosing-leak output filter: a dose must never reach the client."""

import httpx
import pytest

from app.ai.triage import SAFE_DOSING_MESSAGE, DosingLeakFilter, scan_dosing_leak
from tests.conftest import build_app, parse_sse


class TestScan:
    @pytest.mark.parametrize(
        "text",
        [
            "You can give 2.5 mL of infant Tylenol tonight.",
            "The acetaminophen dose would be 160 mg for her weight.",
            "Try 1.25ml of ibuprofen if he's over six months.",
            "Give one 5 ml syringe of Motrin.",
            "0.5 droppers of gas drops usually helps.",
        ],
    )
    def test_dose_near_medication_blocked(self, text: str):
        assert scan_dosing_leak(text)

    @pytest.mark.parametrize(
        "text",
        [
            "No ibuprofen under 6 months — that's a hard rule.",
            "No honey before 12 months.",
            "Never aspirin for children.",
            "Offer 2 oz of formula and see if she settles.",
            "Wait 30 minutes and check her temperature again.",
            "Tylenol exists in infant and children's concentrations — your pediatrician will give the dose.",
        ],
    )
    def test_category_facts_and_safe_text_pass(self, text: str):
        assert not scan_dosing_leak(text)

    def test_strict_mode_blocks_bare_dose_units(self):
        text = "Give 2.5 mL every four hours."
        assert not scan_dosing_leak(text)  # no med name nearby
        assert scan_dosing_leak(text, strict=True)


class TestStreamingFilter:
    def test_dose_split_across_chunks_is_caught(self):
        f = DosingLeakFilter()
        emitted = f.feed("For her weight you could give 2.")
        emitted += f.feed("5 mL of Tylenol and see how the night goes.")
        emitted += f.finalize()
        assert f.triggered
        assert "2.5" not in emitted
        assert "mL" not in emitted
        assert f.final_text == SAFE_DOSING_MESSAGE

    def test_holdback_prevents_partial_leak(self):
        f = DosingLeakFilter()
        # The dose is at the very end; nothing within HOLDBACK chars of it may leak.
        out = f.feed("x" * 100 + " give 2.5 mL of Tylenol")
        assert f.triggered
        assert out == ""

    def test_clean_text_passes_through_completely(self):
        f = DosingLeakFilter()
        text = "Put him down drowsy but awake. White noise as loud as his crying helps."
        out = f.feed(text)
        out += f.finalize()
        assert not f.triggered
        assert out == text
        assert f.final_text == text

    def test_escalate_switches_to_strict(self):
        f = DosingLeakFilter()
        f.escalate()
        f.feed("Roughly 2.5 mL every 4 hours should do it.")
        assert f.triggered


class TestEndToEnd:
    async def test_dose_never_reaches_sse_client_and_message_replaced(
        self, fake_repo, recorder
    ):
        child = fake_repo.seed_child()
        chunks = [
            '<triage level="none" reason="general"/>',
            "For a baby her size, you can give 2.5 mL of infant Tylenol. ",
            "Check again in four hours.",
        ]
        app = build_app(fake_repo, recorder, chunks=chunks)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/chat",
                json={"child_id": str(child.id), "content": "how much tylenol can I give?"},
            )
        events = parse_sse(response.text)
        deltas = "".join(d["text"] for name, d in events if name == "delta")
        assert "2.5" not in deltas
        assert SAFE_DOSING_MESSAGE in deltas

        [assistant] = fake_repo.assistant_messages()
        assert assistant.content == SAFE_DOSING_MESSAGE
        assert any(
            e["source"] == "output_filter" and "dosing_leak" in e["matched_rules"]
            for e in recorder.events
        )
