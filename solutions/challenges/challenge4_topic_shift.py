#!/usr/bin/env python3
"""Challenge 4 reference solution: measure memory across a ten-turn conversation.

    python solutions/challenges/challenge4_topic_shift.py

Runs the fixture conversation, records memory state after every turn, prints
the context-size curve, and checks the three turns that actually matter.

The curve is the deliverable. An agent can produce good answers at every turn
while its context grows without bound - that failure only becomes visible when
the numbers are plotted next to each other.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data" / "challenge_fixtures" / "conversation_10turns.json"
API = os.getenv("AGENT_API_URL", "http://localhost:8080")
SESSION = "challenge4"


async def run_turn(message: str) -> dict:
    """Send one turn and collect both the stream and the memory snapshot."""
    collected = {"answer": "", "tools": [], "intent": None,
                 "topic_changed": False, "topic_event": None}

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST", f"{API}/chat",
            json={"message": message, "session_id": SESSION},
        ) as response:
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                # Buffer and split on the blank line: aiter_text gives
                # arbitrary chunks, and an event split across two of them
                # would otherwise be silently dropped.
                while "\n\n" in buffer:
                    raw, buffer = buffer.split("\n\n", 1)
                    for line in raw.splitlines():
                        if not line.startswith("data: "):
                            continue
                        event = json.loads(line[6:])
                        kind, data = event["type"], event["data"]
                        if kind == "token":
                            collected["answer"] += data
                        elif kind == "step_started":
                            collected["tools"].append(data["tool"])
                        elif kind == "intent_checked":
                            collected["intent"] = data["label"]
                        elif kind == "topic_changed":
                            collected["topic_changed"] = True
                            collected["topic_event"] = data

        memory = (await client.get(f"{API}/sessions/{SESSION}/memory")).json()

    collected["memory"] = memory
    return collected


def sparkline(values: list[int], width: int = 44) -> list[str]:
    """A text bar per turn, scaled to the largest value."""
    peak = max(values) or 1
    return ["#" * max(int(v / peak * width), 1 if v else 0) for v in values]


def check(turn_number: int, expect: dict, result: dict,
          previous_tokens: int) -> list[str]:
    problems = []
    tokens = result["memory"]["context_tokens"]

    if "max_tool_calls" in expect and len(result["tools"]) > expect["max_tool_calls"]:
        problems.append(f"เรียก tool {len(result['tools'])} ครั้ง "
                        f"เกินเพดาน {expect['max_tool_calls']}")
    if "intent" in expect and result["intent"] != expect["intent"]:
        problems.append(f"intent เป็น {result['intent']} "
                        f"ควรเป็น {expect['intent']}")
    if expect.get("topic_changed") is False and result["topic_changed"]:
        problems.append("เปลี่ยนหัวข้อทั้งที่ไม่ควรเปลี่ยน")
    if expect.get("topic_changed") is True and not result["topic_changed"]:
        problems.append("ควรเปลี่ยนหัวข้อแต่ไม่ได้เปลี่ยน")
    if expect.get("context_tokens_decreased") and tokens >= previous_tokens:
        problems.append(f"context ไม่ลดลง ({previous_tokens} -> {tokens})")
    if expect.get("context_preserved") and tokens < previous_tokens * 0.6:
        problems.append(f"context ถูกล้างทั้งที่ไม่ควร "
                        f"({previous_tokens} -> {tokens})")
    for phrase in expect.get("must_contain", []) or []:
        if phrase not in result["answer"]:
            problems.append(f"คำตอบไม่มี '{phrase}'")
    for phrase in expect.get("must_not_contain", []) or []:
        if phrase in result["answer"]:
            problems.append(f"คำตอบไม่ควรมี '{phrase}'")
    return problems


async def main() -> int:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(f"{API}/sessions/{SESSION}")
    except Exception:  # noqa: BLE001
        print(f"\n  ต่อ Agent API ที่ {API} ไม่ได้ - รัน make api ก่อน\n")
        return 1

    conversation = json.loads(FIXTURE.read_text(encoding="utf-8"))
    history, failures = [], []
    previous_tokens = 0

    print("\n=== Challenge 4: Topic Shift Survival ===\n")

    for spec in conversation["turns"]:
        result = await run_turn(spec["message"])
        tokens = result["memory"]["context_tokens"]
        problems = check(spec["turn"], spec["expect"], result, previous_tokens)

        history.append({
            "turn": spec["turn"],
            "message": spec["message"],
            "tokens": tokens,
            "tools": len(result["tools"]),
            "intent": result["intent"],
            "changed": result["topic_changed"],
            "topic": (result["memory"].get("current_topic") or {}).get("label"),
            "archived": len(result["memory"].get("archived_summaries", [])),
            "problems": problems,
        })
        for problem in problems:
            failures.append(f"turn {spec['turn']}: {problem}")
        previous_tokens = tokens

    # ---------- the curve ----------
    values = [h["tokens"] for h in history]
    bars = sparkline(values)

    print(f"  {'turn':<5}{'context':>8}{'tool':>6}{'เปลี่ยน':>9}{'สรุปเก็บ':>10}  กราฟ")
    print("  " + "-" * 74)
    for row, bar in zip(history, bars):
        mark = "yes" if row["changed"] else ""
        flag = " !" if row["problems"] else ""
        print(f"  {row['turn']:<5}{row['tokens']:>8}{row['tools']:>6}"
              f"{mark:>9}{row['archived']:>10}  {bar}{flag}")

    peak = max(values)
    final = values[-1]
    at_shift = next((h for h in history if h["changed"] and h["turn"] > 1), None)

    print("\n  ผลการวิเคราะห์\n")
    print(f"    context สูงสุด        {peak} tokens (turn "
          f"{values.index(peak) + 1})")
    print(f"    context สุดท้าย       {final} tokens")

    if at_shift:
        before = values[at_shift["turn"] - 2]
        after = at_shift["tokens"]
        drop = (before - after) / before * 100 if before else 0
        print(f"    ตอนเปลี่ยนเรื่อง       {before} -> {after} "
              f"(ลดลง {drop:.0f}%)")
        if drop < 40:
            print(f"      ! เกณฑ์ผ่านต้องลดลงอย่างน้อย 40%")

    turn5 = next((h for h in history if h["turn"] == 5), None)
    if turn5:
        print(f"    turn 5 (นอกขอบเขต)   เรียก tool {turn5['tools']} ครั้ง · "
              f"{'ไม่เปลี่ยนหัวข้อ' if not turn5['changed'] else 'เปลี่ยนหัวข้อ (ผิด)'}")

    turn9 = next((h for h in history if h["turn"] == 9), None)
    if turn9:
        print(f"    turn 9 (ย้อนเรื่องเดิม) เรียก tool {turn9['tools']} ครั้ง "
              f"(ควรไม่เกิน 1 เพราะตอบจากสรุปได้)")

    if final >= peak:
        print("\n    ! context ไม่เคยลดลงเลย - กลไกความจำยังไม่ทำงาน")
    else:
        print(f"\n    context ลดลงจากจุดสูงสุด "
              f"{(peak - final) / peak * 100:.0f}% ภายในบทสนทนาเดียว")

    print("\n  " + "-" * 74)
    if failures:
        print(f"  ยังไม่ผ่าน {len(failures)} ข้อ:")
        for failure in failures:
            print(f"    - {failure}")
    else:
        print("  ผ่านครบทุกเกณฑ์")

    output = ROOT / "solutions" / "challenges" / "challenge4_result.json"
    output.write_text(json.dumps(history, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\n  บันทึกผลไว้ที่ {output.relative_to(ROOT)}\n")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
