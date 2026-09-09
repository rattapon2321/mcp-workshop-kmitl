"""Check an answer against the evidence that was actually retrieved.

The failure this prevents is not invention out of nowhere. It is the more
convincing kind: a claim that sounds like a reasonable inference from real
data but is not actually in it. Scenario S4 is exactly that shape - real
severe logs, wrong conclusion.

Running a second, cheap pass whose only job is to check claims against step
results catches a meaningful fraction of those before the user sees them.
"""

from __future__ import annotations

import json

from schemas import GroundingVerdict, StepResult

from . import llm

SYSTEM_PROMPT = """\
You verify whether an answer is supported by the evidence collected.

You are given the tool results that were retrieved and the answer that was
written. For each factual claim in the answer, decide whether the evidence
supports it.

Treat these as UNSUPPORTED:
- a device id, ticket number, count or measurement that does not appear in the evidence
- a causal claim ("X caused Y") where the evidence shows only correlation in time,
  unless the answer says so
- calling something an incident when a maintenance ticket covers the same window
- any statement about a time period outside the data window

Do NOT flag:
- hedged language that already acknowledges uncertainty
- restating evidence in different words
- reasonable summarisation

Be specific. Quote the claim you are rejecting.
"""


async def verify(
    answer: str,
    results: list[StepResult],
    stats: llm.LLMStats | None = None,
    model: str | None = None,
) -> GroundingVerdict:
    evidence = json.dumps(
        [
            {"step": r.step, "tool": r.tool, "result": r.result}
            for r in results if r.ok
        ],
        ensure_ascii=False, default=str,
    )[:12000]

    return await llm.complete_structured(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"EVIDENCE:\n{evidence}\n\nANSWER TO VERIFY:\n{answer}"},
        ],
        GroundingVerdict, stats=stats, model=model,
    )
