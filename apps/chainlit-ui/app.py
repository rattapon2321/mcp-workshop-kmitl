#!/usr/bin/env python3
"""Chainlit frontend for the agent.

Why Chainlit and not a ready-made chat UI: everything the participant builds is
a Python object, and cl.Step renders the agent's Thought -> Action -> Observation
loop directly on screen. Watching the plan appear, the tool calls fire and the
context size change is the difference between understanding an agent loop and
having read about one.

Run:
    make ui        -> http://localhost:8000
"""

from __future__ import annotations

import json
import os

import chainlit as cl
import httpx
from elements import cost_meter, plan_view, topic_banner

AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:8080")

STARTERS = [
    ("ticket ที่ยังไม่ปิด",
     "ticket ที่ยังไม่ปิดตอนนี้มีอะไรบ้าง เรียงตามความรุนแรง"),
    ("หาสาเหตุร่วม",
     "ทำไมช่วงสองสัปดาห์นี้ถึงมีลูกค้าแจ้งเน็ตหลุดซ้ำๆ หลายราย"),
    ("อุปกรณ์ที่น่าเป็นห่วง",
     "ตอนนี้ทั้งโครงข่ายอุปกรณ์ตัวไหนน่าเป็นห่วงที่สุด เพราะอะไร"),
    ("ประเมินผลกระทบก่อนซ่อม",
     "ถ้าจะปิด APE-NBI-03 เพื่อซ่อม จะกระทบลูกค้ากี่ราย ใครบ้าง"),
]


@cl.set_starters
async def starters():
    return [
        cl.Starter(label=label, message=message)
        for label, message in STARTERS
    ]


@cl.on_chat_start
async def start():
    cl.user_session.set("session_id", cl.user_session.get("id"))

    # Show the data window up front. Without it, an audience wonders why
    # "today" is not today - the dataset defines its own present moment.
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{AGENT_API_URL}/health")
            health = response.json()
        tool_count = health.get("mcp", {}).get("tool_count", "?")
        status = f"เชื่อมต่อ MCP Server แล้ว ({tool_count} tools)"
    except Exception as exc:  # noqa: BLE001
        status = f"ยังเชื่อมต่อ Agent API ไม่ได้: {exc}"

    await cl.Message(
        content=(
            "### ผู้ช่วยดูแลโครงข่าย IP-MPLS\n\n"
            f"{status}\n\n"
            "ระบบตอบได้เฉพาะเรื่องโครงข่าย ครอบคลุมพื้นที่ **BKK** และ **NBI** "
            "รวม 10 อุปกรณ์\n\n"
            "ลองเลือกคำถามตัวอย่างด้านล่าง หรือพิมพ์คำถามเอง"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    session_id = "default"  # session_id = cl.user_session.get("session_id") or "default" หากต้องการรัน ID

    answer = cl.Message(content="")
    steps: dict[int, cl.Step] = {}
    plan_step: cl.Step | None = None
    intent_step: cl.Step | None = None
    usage: dict = {}

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST",
            f"{AGENT_API_URL}/chat",
            json={"message": message.content, "session_id": session_id},
        ) as response:
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    raw, buffer = buffer.split("\n\n", 1)
                    payload = None
                    for line in raw.splitlines():
                        if line.startswith("data: "):
                            payload = json.loads(line[6:])
                    if payload is None:
                        continue

                    event_type = payload["type"]
                    data = payload["data"]

                    # -------- intent --------
                    if event_type == "intent_checked":
                        intent_step = cl.Step(
                            name=f"ตรวจสอบขอบเขตคำถาม: {data['label']}",
                            type="tool",
                        )
                        await intent_step.__aenter__()
                        intent_step.output = (
                            f"ผล: **{data['label']}** "
                            f"(ความมั่นใจ {data['confidence']:.0%}, "
                            f"ตัดสินโดย {data.get('decided_by', '-')})\n\n"
                            f"เหตุผล: {data['reason']}"
                        )
                        await intent_step.__aexit__(None, None, None)

                    # -------- topic change --------
                    elif event_type == "topic_changed":
                        await topic_banner(data)

                    # -------- plan --------
                    elif event_type == "plan_created":
                        plan_step = cl.Step(
                            name=f"วางแผน {len(data['steps'])} ขั้นตอน", type="llm"
                        )
                        await plan_step.__aenter__()
                        plan_step.output = plan_view(data)
                        await plan_step.__aexit__(None, None, None)

                    # -------- tool calls --------
                    elif event_type == "step_started":
                        step = cl.Step(
                            name=f"[{data['step']}] {data['tool']}", type="tool"
                        )
                        await step.__aenter__()
                        step.input = json.dumps(
                            data.get("arguments", {}), ensure_ascii=False, indent=2
                        )
                        steps[data["step"]] = step

                    elif event_type == "step_result":
                        step = steps.get(data["step"])
                        if step:
                            if data["ok"]:
                                body = json.dumps(
                                    data["result"], ensure_ascii=False, indent=2
                                )
                                step.output = (
                                    f"สำเร็จใน {data['duration_ms']} ms\n\n"
                                    f"```json\n{body[:2500]}\n```"
                                )
                            else:
                                reason = data.get("error") or data.get("skipped_reason")
                                step.output = f"ไม่สำเร็จ: {reason}"
                            await step.__aexit__(None, None, None)

                    # -------- answer --------
                    elif event_type == "token":
                        await answer.stream_token(data)

                    # -------- grounding --------
                    elif event_type == "grounding_checked":
                        if data.get("supported") is False and data.get("unsupported_claims"):
                            warning = cl.Step(name="ตรวจสอบความถูกต้อง", type="tool")
                            await warning.__aenter__()
                            warning.output = (
                                "พบข้อความที่หลักฐานยังไม่รองรับ:\n"
                                + "\n".join(f"- {c}" for c in data["unsupported_claims"])
                            )
                            await warning.__aexit__(None, None, None)

                    elif event_type == "usage":
                        usage = data

                    elif event_type == "error":
                        await cl.Message(
                            content=f"เกิดข้อผิดพลาด: {data.get('error')}"
                        ).send()

    await answer.send()

    if usage:
        await cost_meter(usage)
