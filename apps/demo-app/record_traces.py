#!/usr/bin/env python3
"""Record live agent runs so they can be replayed offline.

    make demo-record

Run this after every `make reseed`. Traces contain concrete ticket ids and
timestamps, so a stale trace shows data that no longer exists in the database -
which an attentive audience will notice.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

API = os.getenv("AGENT_API_URL", "http://localhost:8080")
TRACE_DIR = Path(__file__).parent / "replay" / "traces"

# The four questions of the demo script, in order.
DEMO_QUESTIONS = [
    ("01-single-source", "ticket ที่ยังไม่ปิดตอนนี้มีอะไรบ้าง เรียงตามความรุนแรง"),
    ("02-cross-service", "ทำไมช่วงสองสัปดาห์นี้ถึงมีลูกค้าแจ้งเน็ตหลุดซ้ำๆ หลายราย"),
    ("03-out-of-scope", "ช่วยเขียนอีเมลลาพักร้อนให้หน่อย"),
    ("04-maintenance", "log ที่ APE-BKK-05 เมื่อ 3 วันก่อนเป็นเหตุเสียจริง หรือเป็นงานที่แจ้งไว้"),
    ("05-not-found", "สถานะของ PE-CNX-99 ตอนนี้เป็นยังไง"),
    ("06-impact", "ถ้าจะปิด APE-NBI-03 เพื่อซ่อม จะกระทบลูกค้ากี่ราย ใครบ้าง"),
]


async def record(name: str, question: str) -> dict:
    events = []
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST", f"{API}/chat",
            json={"message": question, "session_id": f"record-{name}"},
        ) as response:
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    raw, buffer = buffer.split("\n\n", 1)
                    for line in raw.splitlines():
                        if line.startswith("data: "):
                            events.append(json.loads(line[6:]))
    return {"name": name, "question": question, "events": events}


async def main() -> int:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(f"{API}/health")
    except Exception:  # noqa: BLE001
        print(f"\n  Agent API not reachable at {API}. Start it with: make api\n")
        return 1

    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n  Recording {len(DEMO_QUESTIONS)} traces\n")

    for name, question in DEMO_QUESTIONS:
        print(f"  {name} ... ", end="", flush=True)
        trace = await record(name, question)
        (TRACE_DIR / f"{name}.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tokens = sum(1 for e in trace["events"] if e["type"] == "token")
        tools = sum(1 for e in trace["events"] if e["type"] == "step_started")
        print(f"{len(trace['events'])} events, {tools} tool calls, {tokens} tokens")

    print(f"\n  Traces written to {TRACE_DIR}")
    print("  Test with: make demo-offline\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
