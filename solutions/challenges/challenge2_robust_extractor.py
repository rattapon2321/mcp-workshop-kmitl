#!/usr/bin/env python3
"""Challenge 2 reference solution: surviving messy input.

    python solutions/challenges/challenge2_robust_extractor.py

Extends the Workshop 1 extractor with the four defences the noisy fixtures
demand. Each defence is written next to the failure it prevents.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "solutions" / "day1"))
sys.path.insert(0, str(ROOT / "apps" / "agent-api"))

from agent import tokenizer  # noqa: E402
from workshop1_extractor import (  # noqa: E402
    Category, ExtractionResult, Severity, StructuredExtractor,
    TicketExtraction, load_conversations,
)

FIXTURES = ROOT / "data" / "challenge_fixtures" / "noisy_tickets.json"

# Above this, the conversation is trimmed before it reaches the model.
MAX_INPUT_TOKENS = 2000
# Stop the whole run if this many consecutive extractions fail.
CIRCUIT_BREAKER_THRESHOLD = 5


class RobustExtractor(StructuredExtractor):
    """StructuredExtractor plus input hardening."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.consecutive_failures = 0

    # ------------------------------------------------------------------

    @staticmethod
    def _trim(text: str) -> tuple[str, bool]:
        """Keep the head and the tail, drop the middle.

        Noisy ticket 2 is a 40-message thread. Two facts drive this design:

        - The middle of a long context is where models lose information
          (Module 2), so trimming the middle costs less accuracy than
          trimming either end.
        - The first messages describe the symptom and the last describe the
          resolution. Those are exactly the fields being extracted.
        """
        if tokenizer.count(text) <= MAX_INPUT_TOKENS:
            return text, False

        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) <= 12:
            # Few but very long lines: fall back to character truncation.
            return text[:6000] + "\n[... ตัดข้อความส่วนกลางออก ...]", True

        head, tail = lines[:6], lines[-6:]
        dropped = len(lines) - 12
        return (
            "\n".join(head)
            + f"\n[... ตัดข้อความตรงกลางออก {dropped} บรรทัด ...]\n"
            + "\n".join(tail),
            True,
        )

    @staticmethod
    def _has_injection_marker(text: str) -> bool:
        """Detect obvious instruction-injection attempts.

        Detection alone is NOT the defence - the delimiters and the system
        prompt are. This only exists so the attempt can be logged and the
        confidence lowered, because something that tries to hijack the
        extractor is a ticket a human should look at.
        """
        markers = [
            "ignore all previous", "ignore previous", "disregard the above",
            "developer mode", "system prompt", "you are now",
            "ไม่ต้องสนใจคำสั่ง", "ลืมคำสั่งก่อนหน้า",
        ]
        lowered = text.lower()
        return any(marker in lowered for marker in markers)

    # ------------------------------------------------------------------

    async def extract_safe(self, text: str) -> tuple[ExtractionResult, dict]:
        notes = {"trimmed": False, "injection_detected": False,
                 "input_tokens": tokenizer.count(text)}

        if self.consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            # Bonus task 2. Without this, a systemic problem - a wrong model
            # name, an endpoint returning 500 - burns the entire token budget
            # retrying every remaining row three times.
            notes["circuit_breaker"] = True
            return ExtractionResult(
                ok=False, attempts=0,
                errors=[f"circuit breaker: ล้มเหลวติดกัน "
                        f"{self.consecutive_failures} ครั้ง หยุดประมวลผล"],
                fallback_used=True,
            ), notes

        if self._has_injection_marker(text):
            notes["injection_detected"] = True

        prepared, trimmed = self._trim(text)
        notes["trimmed"] = trimmed
        notes["sent_tokens"] = tokenizer.count(prepared)

        result = await self.extract(prepared)

        if result.ok and result.data:
            # An extraction from text that tried to hijack the extractor is
            # not trustworthy at face value, even when it validates.
            if notes["injection_detected"]:
                result.data.confidence = min(result.data.confidence, 0.4)
            # Bonus task 1: distinguish "no information" from "extraction
            # failed". Both produce a null device, but they need different
            # follow-up, so the difference must survive into the output.
            if result.data.affected_device is None and notes["input_tokens"] < 30:
                notes["reason"] = "ข้อความสั้นเกินกว่าจะสรุปได้ - ไม่ใช่ความผิดพลาดของระบบ"

        self.consecutive_failures = 0 if result.ok else self.consecutive_failures + 1
        return result, notes


# --------------------------------------------------------------------------

def check_expectations(fixture: dict, result: ExtractionResult) -> list[str]:
    """Verify the specific trap each fixture sets."""
    expect = fixture.get("expect", {})
    problems = []

    if not result.data:
        return ["ไม่มีข้อมูลกลับมาเลย"]

    if "affected_device" in expect and expect["affected_device"] is None:
        if result.data.affected_device is not None:
            problems.append(
                f"เดาอุปกรณ์ขึ้นมาเอง: {result.data.affected_device} "
                f"(ควรเป็น null)"
            )
    if "affected_device" in expect and expect["affected_device"]:
        if result.data.affected_device != expect["affected_device"]:
            problems.append(f"อุปกรณ์ผิด: ได้ {result.data.affected_device}, "
                            f"ควรเป็น {expect['affected_device']}")
    if "confidence_below" in expect:
        if result.data.confidence >= expect["confidence_below"]:
            problems.append(f"confidence สูงเกินไป: {result.data.confidence} "
                            f"(ควรต่ำกว่า {expect['confidence_below']})")
    for phrase in expect.get("must_not_contain", []):
        blob = result.data.model_dump_json()
        if phrase.lower() in blob.lower():
            problems.append(f"ผลลัพธ์มีร่องรอยของคำสั่งที่ฝังมา: '{phrase}'")
    return problems


async def main() -> int:
    extractor = RobustExtractor(TicketExtraction)

    noisy = json.loads(FIXTURES.read_text(encoding="utf-8"))
    normal = load_conversations(20)
    total = len(noisy) + len(normal)

    print(f"\n=== Challenge 2: Schema Under Pressure ({total} ใบ) ===\n")
    print(f"  {'id':<12}{'ok':<5}{'retry':<7}{'in→sent':<12}{'หมายเหตุ'}")
    print("  " + "-" * 70)

    failures, all_results = [], []

    for fixture in noisy:
        result, notes = await extractor.extract_safe(fixture["conversation"])
        problems = check_expectations(fixture, result)
        all_results.append((fixture["id"], result, notes, problems))

        flags = []
        if notes["trimmed"]:
            flags.append("ตัดข้อความ")
        if notes["injection_detected"]:
            flags.append("พบ injection")
        if notes.get("reason"):
            flags.append("ข้อมูลไม่พอ")

        print(f"  {fixture['id']:<12}{'yes' if result.ok else 'NO':<5}"
              f"{result.attempts:<7}"
              f"{notes['input_tokens']}→{notes.get('sent_tokens', '-'):<7}"
              f"{' · '.join(flags)}")
        for problem in problems:
            print(f"               ! {problem}")
            failures.append(f"{fixture['id']}: {problem}")

    for ticket_id, conversation in normal:
        result, notes = await extractor.extract_safe(conversation)
        all_results.append((ticket_id, result, notes, []))
        if not result.ok:
            failures.append(f"{ticket_id}: สกัดไม่สำเร็จ")
            
            # --- เพิ่มบรรทัดปริ้นท์ Error ตรงนี้ ---
            print(f"           🚨 สาเหตุ: {result.errors}")
            
        print(f"  {ticket_id:<12}{'yes' if result.ok else 'NO':<5}"
              f"{result.attempts:<7}{notes['input_tokens']}→"
              f"{notes.get('sent_tokens', '-'):<7}")

    ok = sum(1 for _, r, _, p in all_results if r.ok and not p)
    tokens = sum(r.total_tokens for _, r, _, _ in all_results)
    retried = sum(1 for _, r, _, _ in all_results if r.attempts > 1)

    print("\n  " + "-" * 70)
    print(f"  ผ่านเกณฑ์ทั้งหมด   {ok}/{total}")
    print(f"  ต้อง retry        {retried}")
    print(f"  token รวม         {tokens:,}")
    print(f"  token/ใบ เฉลี่ย    {tokens // max(total, 1):,}")

    # The workshop caps total token use at 2x the ideal, so a system that
    # "passes" only by retrying everything three times does not count.
    ideal = (tokens / max(retried + total, 1)) * total
    print(f"  เทียบเพดาน 2 เท่า  "
          f"{'ผ่าน' if tokens <= ideal * 2 else 'เกิน'}")

    if failures:
        print(f"\n  ยังไม่ผ่าน {len(failures)} ข้อ:")
        for failure in failures:
            print(f"    - {failure}")
    else:
        print("\n  ผ่านครบทุกข้อ")
    print()
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
