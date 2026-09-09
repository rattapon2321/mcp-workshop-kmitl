#!/usr/bin/env python3
"""Evaluate answer quality against the golden question set.

    make eval

Reports per level, because a single aggregate number hides the thing that
matters. A system can score well overall while failing every L6 question -
that is, while confidently inventing answers - and that failure mode is the
one this project cares most about.

For results that can be compared across runs, pin the dataset:
    DEMO_NOW=2026-01-15T10:00:00+07:00
    SEED_RANDOM_SEED=42
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_DIR = ROOT / "data" / "questions"
API = os.getenv("AGENT_API_URL", "http://localhost:8080")
OUTPUT = ROOT / "eval" / "results"


def load_questions() -> dict[str, list[dict]]:
    """Golden questions grouped by level."""
    by_level: dict[str, list[dict]] = {}
    for path in sorted(QUESTIONS_DIR.glob("L*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        level = data["meta"]["level"]
        by_level[level] = data.get("questions", []) or []
    return by_level


async def ask(question: str, session_id: str) -> dict:
    """Run one question and collect everything the agent emitted."""
    collected = {"answer": "", "tools": [], "intent": None,
                 "usage": {}, "plan": None, "grounding": None, "error": None}
    started = time.time()

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST", f"{API}/chat",
            json={"message": question, "session_id": session_id},
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
                        elif kind == "plan_created":
                            collected["plan"] = data
                        elif kind == "usage":
                            collected["usage"] = data
                        elif kind == "grounding_checked":
                            collected["grounding"] = data
                        elif kind == "error":
                            collected["error"] = data.get("error")

    collected["latency_ms"] = int((time.time() - started) * 1000)
    return collected


def score(question: dict, result: dict) -> dict:
    """Apply the expectations declared alongside each question."""
    expect = question.get("expect", {}) or {}
    checks: list[tuple[str, bool, str]] = []
    answer = result["answer"]

    if "intent" in expect:
        ok = result["intent"] == expect["intent"]
        checks.append(("intent", ok, f"expected {expect['intent']}, got {result['intent']}"))

    if "max_tool_calls" in expect:
        n = len(result["tools"])
        checks.append(("max_tool_calls", n <= expect["max_tool_calls"],
                       f"used {n}, limit {expect['max_tool_calls']}"))

    for phrase in expect.get("must_contain", []) or []:
        checks.append((f"contains:{phrase}", phrase in answer, ""))

    for phrase in expect.get("must_not_contain", []) or []:
        checks.append((f"absent:{phrase}", phrase not in answer, ""))

    for tool in question.get("expected_tools", []) or []:
        checks.append((f"tool:{tool}", tool in result["tools"], ""))

    if expect.get("must_cite"):
        # Citation is checked by looking for the store name in the answer.
        for source in expect["must_cite"]:
            name = {"postgres": "PostgreSQL", "neo4j": "Neo4j",
                    "opensearch": "OpenSearch"}[source]
            checks.append((f"cite:{source}", name in answer, ""))

    if result["error"]:
        checks.append(("no_error", False, result["error"]))

    passed = sum(1 for _, ok, _ in checks if ok)
    return {
        "id": question["id"],
        "passed": passed,
        "total": len(checks),
        "ok": passed == len(checks) and len(checks) > 0,
        "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
        "tools_used": result["tools"],
        "tokens": result["usage"].get("total_tokens", 0),
        "latency_ms": result["latency_ms"],
        "grounded": (result["grounding"] or {}).get("supported"),
    }


async def main() -> int:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(f"{API}/health")
    except Exception:  # noqa: BLE001
        print(f"\n  Agent API not reachable at {API}. Start it with: make api\n")
        return 1

    by_level = load_questions()
    summary, all_results = {}, []

    for level, questions in by_level.items():
        if not questions:
            continue
        print(f"\n{'=' * 62}\n  {level}  ({len(questions)} questions)\n{'=' * 62}")
        level_results = []
        for question in questions:
            # A fresh session per question, so memory from one does not leak
            # into the next and quietly change the result.
            result = await ask(question["question"], f"eval-{question['id']}")
            scored = score(question, result)
            level_results.append(scored)
            all_results.append({**scored, "level": level})
            mark = "PASS" if scored["ok"] else "FAIL"
            print(f"  [{mark}] {scored['id']:<6} {scored['passed']}/{scored['total']}  "
                  f"{scored['tokens']:>6} tok  {scored['latency_ms']:>6} ms")
            for check in scored["checks"]:
                if not check["ok"]:
                    print(f"           - {check['name']} {check['detail']}")

        passed = sum(1 for r in level_results if r["ok"])
        summary[level] = {"passed": passed, "total": len(level_results)}

    print(f"\n{'=' * 62}\n  SUMMARY\n{'=' * 62}")
    for level, stats in summary.items():
        rate = stats["passed"] / stats["total"] * 100 if stats["total"] else 0
        print(f"  {level:<4} {stats['passed']:>3}/{stats['total']:<3}  {rate:5.1f}%")

    total_passed = sum(s["passed"] for s in summary.values())
    total_all = sum(s["total"] for s in summary.values())
    print(f"\n  TOTAL {total_passed}/{total_all}")
    print(f"  tokens {sum(r['tokens'] for r in all_results):,}")

    if "L6" in summary and summary["L6"]["passed"] < summary["L6"]["total"]:
        print("\n  NOTE: an L6 failure means the system invented an answer "
              "instead of saying it did not know. Treat that as more serious "
              "than a wrong tool choice.")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "latest.json").write_text(
        json.dumps({"summary": summary, "results": all_results},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  written to {OUTPUT / 'latest.json'}\n")
    return 0 if total_passed == total_all else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
