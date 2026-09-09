"""Memory management across a ten-turn conversation - challenge 4.

What is actually being measured is the shape of the context-size curve.
A curve that only ever rises means the memory layer is not working, no matter
how good the individual answers look.
"""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import needs_llm

pytestmark = needs_llm

API = "http://localhost:8080"


async def _turn(message: str, session_id: str) -> dict:
    collected = {"answer": "", "tools": [], "intent": None,
                 "topic_changed": False, "topic_event": None}
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST", f"{API}/chat",
            json={"message": message, "session_id": session_id},
        ) as response:
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
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

        memory = (await client.get(f"{API}/sessions/{session_id}/memory")).json()
    collected["memory"] = memory
    return collected


async def test_ten_turn_conversation(conversation, capsys):
    session = "test-topic-shift"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.delete(f"{API}/sessions/{session}")

    history, failures = [], []

    for spec in conversation["turns"]:
        result = await _turn(spec["message"], session)
        expect = spec["expect"]
        tokens = result["memory"]["context_tokens"]
        history.append({"turn": spec["turn"], "tokens": tokens,
                        "tools": len(result["tools"]),
                        "changed": result["topic_changed"]})

        n = spec["turn"]
        if "max_tool_calls" in expect and len(result["tools"]) > expect["max_tool_calls"]:
            failures.append(f"turn {n}: used {len(result['tools'])} tools, "
                            f"limit {expect['max_tool_calls']}")
        if "intent" in expect and result["intent"] != expect["intent"]:
            failures.append(f"turn {n}: intent {result['intent']}, "
                            f"expected {expect['intent']}")
        if expect.get("topic_changed") is False and result["topic_changed"]:
            failures.append(f"turn {n}: topic changed but should not have")
        if expect.get("topic_changed") is True and not result["topic_changed"]:
            failures.append(f"turn {n}: topic should have changed but did not")
        if expect.get("context_tokens_decreased"):
            previous = history[-2]["tokens"] if len(history) > 1 else 0
            if tokens >= previous:
                failures.append(f"turn {n}: context {previous} -> {tokens}, "
                                "expected a decrease")
        for phrase in expect.get("must_contain", []) or []:
            if phrase not in result["answer"]:
                failures.append(f"turn {n}: answer missing '{phrase}'")
        for phrase in expect.get("must_not_contain", []) or []:
            if phrase in result["answer"]:
                failures.append(f"turn {n}: answer should not contain '{phrase}'")

    with capsys.disabled():
        print("\n\n  turn  context_tokens  tools  topic_changed")
        for row in history:
            bar = "#" * min(row["tokens"] // 120, 40)
            print(f"  {row['turn']:>4}  {row['tokens']:>13}  {row['tools']:>5}  "
                  f"{'yes' if row['changed'] else '':<13} {bar}")
        peak = max(h["tokens"] for h in history)
        final = history[-1]["tokens"]
        print(f"\n  peak {peak}  final {final}")
        if final >= peak:
            print("  context never came down - the memory layer is not pruning\n")

    assert not failures, "\n  ".join([""] + failures)
