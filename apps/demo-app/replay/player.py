"""Replay recorded traces as if the agent were running live.

Insurance for demonstrations. A recorded trace streams back with the same
events and the same token-by-token pacing as a live run, so a demo survives a
VPN outage, a GPU queue, or a venue with no network at all.

Traces are matched by similarity to the recorded question, so a presenter who
types a slight variation still gets the right trace.
"""

from __future__ import annotations

import asyncio
import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import AsyncIterator

TRACE_DIR = Path(__file__).parent / "traces"

# Pacing. Real generation is not instant, and a replay that dumps everything at
# once looks fake and gives the audience no time to read.
TOKEN_DELAY = 0.018
STEP_DELAY = 0.45
PLAN_DELAY = 1.2


def load_traces() -> list[dict]:
    traces = []
    for path in sorted(TRACE_DIR.glob("*.json")):
        try:
            traces.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return traces


def find_trace(question: str) -> dict | None:
    """Closest recorded question wins, as long as it is close enough."""
    traces = load_traces()
    if not traces:
        return None

    def similarity(trace: dict) -> float:
        return SequenceMatcher(None, question.strip(), trace["question"].strip()).ratio()

    best = max(traces, key=similarity)
    return best if similarity(best) > 0.55 else None


async def replay(question: str) -> AsyncIterator[tuple[str, object]]:
    """Yield (event_type, data) pairs with realistic pacing."""
    trace = find_trace(question)
    if trace is None:
        yield ("error", {"error": "ไม่พบ trace ที่บันทึกไว้สำหรับคำถามนี้ "
                                  "ใช้ make demo-record เพื่อบันทึกเพิ่ม"})
        yield ("done", {"reason": "no_trace"})
        return

    for event in trace["events"]:
        kind, data = event["type"], event["data"]

        if kind == "token":
            # Tokens were recorded individually; replay them one at a time.
            await asyncio.sleep(TOKEN_DELAY)
        elif kind == "plan_created":
            await asyncio.sleep(PLAN_DELAY)
        elif kind in ("step_started", "step_result"):
            await asyncio.sleep(STEP_DELAY)
        else:
            await asyncio.sleep(0.15)

        yield (kind, data)
