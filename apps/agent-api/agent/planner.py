"""Turn a question into an executable plan.

The plan is data, not prose. That single decision is what makes the rest of
the agent testable: a plan can be inspected, validated against the tool list,
shown to the user, replayed, and compared against an expected shape in a test.

Two properties matter more than anything else in the produced plan:

  1. Dependencies are explicit. Step 3 declaring depends_on: [2] is what lets
     the executor pass a result forward - and lets independent steps run
     concurrently instead of in a needless sequence.

  2. Every step names a tool that actually exists with arguments that fit its
     schema. This is enforced after generation, not trusted.
"""

from __future__ import annotations

import json

from schemas import Plan

from . import llm, mcp_client

SYSTEM_PROMPT = """\
You plan how to answer questions about an IP-MPLS network using the tools listed
below. You do not answer the question - you produce the plan that will.

Rules:

1. Use the fewest steps that fully answer the question. Do not add steps that
   collect information the answer will not use.

2. Declare dependencies honestly. A step goes in depends_on ONLY if it needs
   that step's output. Steps with no dependency between them will be run
   concurrently, so a false dependency costs real time.

3. When a value is not known until an earlier step runs, leave it out of
   `arguments` and record it in `argument_from` as
   {"argument_name": "step.N.path.to.value"}.

4. Time ranges are relative names only: last_1h, last_6h, last_24h, last_3d,
   last_7d, last_14d, last_30d, last_90d. Never write a date.

Domain knowledge you are expected to apply:

- When several customers on DIFFERENT access devices report the same symptom,
  the cause is usually a shared upstream device. Find the devices from the
  tickets, then call get_upstream_devices on all of them together, then check
  that device's logs for the same period. Do not stop at the tickets.

- Logs show symptoms; configuration shows causes. An adjacency problem needs
  the configuration of BOTH ends, and the far end may be at another site.

- Severe logs may be planned maintenance. If a question is about whether
  something is an incident, check tickets with category "maintenance" covering
  the same window before concluding anything.

- The network has exactly ten devices across BKK and NBI. If the question names
  something outside that, plan a single list_devices step so the answer can say
  plainly that it does not exist.
"""


async def create_plan(
    question: str,
    context: list[dict] | None = None,
    stats: llm.LLMStats | None = None,
    model: str | None = None,
) -> Plan:
    client = mcp_client.get()
    tools = await client.list_tools()

    tool_catalogue = "\n\n".join(
        f"### {tool['name']}\n{tool['description'].strip()}\n"
        f"arguments: {json.dumps(tool['input_schema'].get('properties', {}), ensure_ascii=False)}"
        for tool in tools
    )

    # The model is told what "now" means before it plans anything involving time.
    clock_info = await client.read_resource("clock://now")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Available tools:\n\n{tool_catalogue}"},
        {"role": "system", "content": f"Current time context:\n{clock_info}"},
    ]
    if context:
        messages.append({
            "role": "system",
            "content": "Conversation so far:\n" + "\n".join(
                f"{turn['role']}: {turn['content'][:400]}" for turn in context[-6:]
            ),
        })
    messages.append({"role": "user", "content": question})

    plan = await llm.complete_structured(messages, Plan, stats=stats, model=model)
    return validate_plan(plan, tools)


def validate_plan(plan: Plan, tools: list[dict]) -> Plan:
    """Drop steps that cannot run, and repair obviously broken dependencies.

    A hallucinated tool name is far better caught here than at execution time,
    where it costs a round trip and produces a confusing error for the user.
    """
    known = {tool["name"] for tool in tools}
    valid_steps = []
    dropped: list[str] = []

    for step in plan.steps:
        if step.tool not in known:
            dropped.append(step.tool)
            continue
        # A dependency on a step that does not exist would deadlock the executor.
        step.depends_on = [d for d in step.depends_on if d < step.step]
        valid_steps.append(step)

    plan.steps = valid_steps

    # --- ส่วนที่เพิ่มเติมเข้ามา: บังคับผูก depends_on ให้ Step หลัง ถ้ามีหลายขั้นตอนแล้วไม่ได้ใส่ ---
    if len(plan.steps) >= 3 and not any(step.depends_on for step in plan.steps):
        for i in range(1, len(plan.steps)):
            # ให้ Step ที่ i พึ่งพาผลลัพธ์จาก Step ก่อนหน้า (i)
            plan.steps[i].depends_on = [plan.steps[i - 1].step]

    if dropped:
        plan.reasoning += (
            f"\n\n[ระบบตัดขั้นตอนที่อ้างถึง tool ที่ไม่มีอยู่จริงออก: {', '.join(dropped)}]"
        )
    return plan