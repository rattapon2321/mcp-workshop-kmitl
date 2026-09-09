"""Turn step results into an answer a network engineer can act on.

The synthesiser is where citations are enforced. An answer without a source is
an answer nobody can verify, and an operator who cannot verify a claim either
ignores the system or acts on something wrong. Both are failures.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from schemas import Plan, StepResult

from . import llm

SYSTEM_PROMPT = """\
You are a network operations assistant for an IP-MPLS backbone. Write the final
answer in Thai, for an engineer who will act on it.

Rules:

1. Answer the question that was asked, first. Do not open with a summary of
   what you did.

2. Cite the source of every factual claim, inline and briefly:
   (PostgreSQL: ticket TK-25-00012), (Neo4j: topology), (OpenSearch: log)

3. Use only what is in the evidence. If the evidence does not support a
   conclusion, say what is missing and what would be needed to settle it.
   "ยังสรุปไม่ได้" is an acceptable answer. Inventing a device, number or
   ticket is not.

4. If a step failed or returned nothing, say so rather than quietly omitting it.

5. When a result was truncated, say the number is a partial count.

6. When something looks alarming but a maintenance ticket covers the same
   window, say plainly that it is planned work and reference the ticket.

7. End with a short "สิ่งที่ควรทำต่อ" only when there is a concrete next action.
   Do not pad.

Formatting: short paragraphs, a table when comparing more than three things,
bold only for the single most important finding.
"""


def _build_evidence(plan: Plan, results: list[StepResult]) -> str:
    blocks = []
    for result in results:
        step = next((s for s in plan.steps if s.step == result.step), None)
        purpose = step.purpose if step else ""
        if result.ok:
            payload = json.dumps(result.result, ensure_ascii=False, default=str)[:6000]
            blocks.append(
                f"--- Step {result.step}: {result.tool} ---\n"
                f"Purpose: {purpose}\nResult: {payload}"
            )
        else:
            reason = result.error or result.skipped_reason or "unknown"
            blocks.append(
                f"--- Step {result.step}: {result.tool} (FAILED) ---\n"
                f"Purpose: {purpose}\nReason: {reason}"
            )
    return "\n\n".join(blocks)


async def synthesize_stream(
    question: str,
    plan: Plan,
    results: list[StepResult],
    context: list[dict] | None = None,
    stats: llm.LLMStats | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system",
         "content": f"Plan that was executed:\n{plan.goal}\n{plan.reasoning}"},
        {"role": "system", "content": f"EVIDENCE:\n{_build_evidence(plan, results)}"},
    ]
    if context:
        messages.append({
            "role": "system",
            "content": "Earlier in this conversation:\n" + "\n".join(
                f"{turn['role']}: {turn['content'][:300]}" for turn in context[-4:]
            ),
        })
    messages.append({"role": "user", "content": question})

    async for token in llm.stream(messages, stats=stats, model=model):
        yield token


async def answer_general(
    question: str,
    context: list[dict] | None = None,
    stats: llm.LLMStats | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    """Answer a networking knowledge question without touching any tool."""
    messages = [
        {
            "role": "system",
            "content": (
                "ตอบคำถามความรู้ทั่วไปด้านเครือข่ายเป็นภาษาไทย กระชับและถูกต้อง\n"
                "อย่าอ้างอิงข้อมูลจากระบบใดๆ เพราะคำถามนี้ไม่ได้ค้นข้อมูลจริง\n"
                "ถ้าคำถามใกล้เคียงกับข้อมูลที่ระบบมี ให้แนะนำท้ายคำตอบว่า "
                "ถามแบบเจาะจงกับข้อมูลจริงได้อย่างไร"
            ),
        }
    ]
    if context:
        messages.extend(context[-4:])
    messages.append({"role": "user", "content": question})

    async for token in llm.stream(messages, stats=stats, model=model):
        yield token
