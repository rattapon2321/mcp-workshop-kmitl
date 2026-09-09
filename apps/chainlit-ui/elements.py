"""Custom UI elements.

The token and cost meter is not decoration. On a local model there is no
per-token price, so the meaningful cost is GPU time - latency, throughput and
how much context is being carried into every call. Putting those numbers on
screen for three days changes how participants write prompts far more
effectively than a slide about it does.
"""

from __future__ import annotations

import chainlit as cl


def plan_view(plan: dict) -> str:
    """Render a plan as a Mermaid diagram plus a table.

    The diagram makes dependencies obvious at a glance: steps side by side ran
    concurrently, steps in a chain had to wait.
    """
    lines = [f"**เป้าหมาย**: {plan['goal']}", "", f"{plan['reasoning']}", ""]

    lines += ["```mermaid", "flowchart TD"]
    for step in plan["steps"]:
        label = f"{step['step']}. {step['tool']}"
        lines.append(f'    S{step["step"]}["{label}"]')
    for step in plan["steps"]:
        for dependency in step.get("depends_on", []):
            lines.append(f"    S{dependency} --> S{step['step']}")
    lines.append("```")

    lines += ["", "| ขั้น | เครื่องมือ | ทำเพื่อ | รอขั้น |", "|---|---|---|---|"]
    for step in plan["steps"]:
        depends = ", ".join(str(d) for d in step.get("depends_on", [])) or "-"
        lines.append(
            f"| {step['step']} | `{step['tool']}` | {step['purpose']} | {depends} |"
        )

    sources = ", ".join(plan.get("expected_sources", [])) or "-"
    lines += ["", f"**แหล่งข้อมูลที่คาดว่าจะใช้**: {sources}"]
    return "\n".join(lines)


async def topic_banner(data: dict) -> None:
    """Announce a topic change and show the context actually shrinking.

    This is the visible proof that memory management is doing something. Without
    it, participants have to take the mechanism on faith.
    """
    before = data.get("context_tokens_before", 0)
    after = data.get("context_tokens_after", 0)
    saved = before - after

    body = [
        "### เปลี่ยนหัวข้อการสนทนา",
        "",
        f"**เหตุผล**: {data.get('reason')}",
        "",
        f"ขนาด context: `{before}` → `{after}` tokens"
        + (f"  (**ลดลง {saved}**)" if saved > 0 else ""),
    ]
    if data.get("archived_summaries"):
        body += ["", "**สรุปเรื่องเดิมที่เก็บไว้แทน detail ทั้งหมด**:"]
        body += [f"- {s}" for s in data["archived_summaries"]]

    await cl.Message(content="\n".join(body), author="ระบบความจำ").send()


async def cost_meter(usage: dict) -> None:
    """Show what the turn actually cost in GPU terms."""
    rows = [
        ("Token ที่ส่งเข้า (prompt)", usage.get("prompt_tokens", 0)),
        ("Token ที่สร้างออกมา", usage.get("completion_tokens", 0)),
        ("รวม", usage.get("total_tokens", 0)),
        ("ขนาด context ปัจจุบัน", usage.get("context_tokens", 0)),
        ("เรียก LLM", usage.get("llm_calls", 0)),
        ("เรียก tool", usage.get("tool_calls", 0)),
        ("เวลารวม (ms)", usage.get("latency_ms", 0)),
        ("ความเร็ว (tokens/sec)", usage.get("tokens_per_second", 0)),
    ]
    table = "\n".join(f"| {label} | {value} |" for label, value in rows)

    note = ""
    context_tokens = usage.get("context_tokens", 0)
    if context_tokens > 4000:
        note = (
            "\n\n> context เริ่มใหญ่แล้ว ถ้าเปลี่ยนเรื่องระบบจะสรุปแล้วตัดทิ้งให้อัตโนมัติ"
        )

    await cl.Message(
        content=f"| รายการ | ค่า |\n|---|---|\n{table}{note}",
        author="มาตรวัดต้นทุน",
    ).send()
