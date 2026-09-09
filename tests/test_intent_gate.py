"""Intent gate.

The fast-path tests need nothing running - that is deliberate. The cheap
deterministic layer should be testable and correct on its own, before any
model is involved.
"""

from __future__ import annotations

import pytest
from agent.intent import fast_path, refusal_message
from conftest import needs_llm
from schemas import IntentLabel


class TestFastPath:
    @pytest.mark.parametrize("message", [
        "สถานะของ APE-NBI-03 เป็นยังไง",
        "ticket TK-25-00003 มีรายละเอียดอะไร",
        "PE-BKK-02 มีปัญหาอะไร",
    ])
    def test_identifier_means_in_scope(self, message):
        """An explicit device or ticket id is unambiguous evidence."""
        result = fast_path(message)
        assert result is not None
        assert result.label == IntentLabel.IN_SCOPE

    @pytest.mark.parametrize("message", [
        "วันนี้อากาศเป็นยังไง",
        "ช่วยเขียนอีเมลลาพักร้อนให้หน่อย",
        "หุ้น NT น่าซื้อไหม",
    ])
    def test_off_domain_refused(self, message):
        result = fast_path(message)
        assert result is not None
        assert result.label == IntentLabel.OUT_OF_SCOPE

    def test_mixed_signal_is_not_refused(self):
        """A domain question with an incidental off-domain word must survive.

        'ส่งรายงาน log ให้ทีมก่อนไปกินข้าว' is a real request. A gate that
        refuses it because of the word for lunch is worse than no gate.
        """
        result = fast_path("ส่งรายงาน log ของอุปกรณ์ให้ทีมก่อนไปกินข้าว")
        assert result is None or result.label != IntentLabel.OUT_OF_SCOPE

    @pytest.mark.parametrize("message", [
        "ticket ที่ยังไม่ปิดของอุปกรณ์ตัวไหนบ้าง",
        "log ของ interface ที่ down มีอะไรบ้าง",
    ])
    def test_multiple_domain_terms_means_in_scope(self, message):
        result = fast_path(message)
        assert result is not None and result.label == IntentLabel.IN_SCOPE

    def test_vague_reference_asks_for_clarification(self):
        result = fast_path("ดูให้หน่อยว่าปกติไหม")
        assert result is not None
        assert result.label == IntentLabel.NEEDS_CLARIFICATION


class TestRefusalMessage:
    def test_refusal_states_scope_and_gives_an_example(self):
        from schemas import IntentResult

        text = refusal_message(IntentResult(
            label=IntentLabel.OUT_OF_SCOPE, confidence=0.9, reason="test"
        ))
        assert "โครงข่าย" in text
        assert "ticket" in text, "a refusal must show what CAN be asked"

    def test_clarification_lists_what_is_missing(self):
        from schemas import IntentResult

        text = refusal_message(IntentResult(
            label=IntentLabel.NEEDS_CLARIFICATION, confidence=0.8, reason="test",
            missing_information=["ชื่ออุปกรณ์"],
        ))
        assert "ชื่ออุปกรณ์" in text


@needs_llm
class TestClassifier:
    @pytest.mark.parametrize("qid,expected", [
        ("Q05", IntentLabel.GENERAL_KNOWLEDGE),
        ("Q26", IntentLabel.NEEDS_CLARIFICATION),
        ("Q27", IntentLabel.NEEDS_CLARIFICATION),
    ])
    async def test_ambiguous_cases_reach_the_model(self, questions, qid, expected):
        """These are exactly the cases the fast path must NOT decide alone."""
        from agent import intent

        question = questions[qid]["question"]
        result = await intent.classify(question)
        assert result.label == expected
