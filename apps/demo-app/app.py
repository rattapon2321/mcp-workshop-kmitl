#!/usr/bin/env python3
"""Chainlit UI for the reference demo app.

Differs from the participant UI in three ways, all of them about being safe
and legible in front of an audience:

  - starters follow the demo script order
  - a status table is shown on start, including the data window
  - replay mode plays a recorded trace when no live backend is available
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "chainlit-ui"))

import chainlit as cl  # noqa: E402
import httpx  # noqa: E402
import health_page  # noqa: E402
from elements import cost_meter, plan_view, topic_banner  # noqa: E402
from replay.player import replay  # noqa: E402
from starters import DEMO_STARTERS  # noqa: E402

AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:8080")
DEMO_MODE = os.getenv("DEMO_MODE", "live")


@cl.set_starters
async def starters():
    return [cl.Starter(label=s["label"], message=s["message"]) for s in DEMO_STARTERS]


@cl.on_chat_start
async def start():
    banner = health_page.render() if DEMO_MODE == "live" else (
        "### โหมด replay\n\nเล่นจาก trace ที่บันทึกไว้ ไม่ต้องใช้ LLM หรือฐานข้อมูล"
    )
    mode_note = "" if DEMO_MODE == "live" else "\n\n> กำลังทำงานในโหมด replay"
    await cl.Message(
        content=f"## ผู้ช่วยดูแลโครงข่าย IP-MPLS\n\n{banner}{mode_note}"
    ).send()


async def _events(question: str, session_id: str):
    """Yield (type, data) from either the live API or a recorded trace."""
    if DEMO_MODE == "replay":
        async for item in replay(question):
            yield item
        return

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST", f"{AGENT_API_URL}/chat",
            json={"message": question, "session_id": session_id},
        ) as response:
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    raw, buffer = buffer.split("\n\n", 1)
                    for line in raw.splitlines():
                        if line.startswith("data: "):
                            event = json.loads(line[6:])
                            yield (event["type"], event["data"])


@cl.on_message
async def on_message(message: cl.Message):
    session_id = cl.user_session.get("id") or "demo"
    answer = cl.Message(content="")
    steps: dict[int, cl.Step] = {}
    usage: dict = {}

    async for kind, data in _events(message.content, session_id):
        if kind == "intent_checked":
            step = cl.Step(name=f"ตรวจสอบขอบเขตคำถาม: {data['label']}", type="tool")
            await step.__aenter__()
            step.output = (f"**{data['label']}** "
                           f"(มั่นใจ {data['confidence']:.0%} · "
                           f"ตัดสินโดย {data.get('decided_by','-')})\n\n{data['reason']}")
            await step.__aexit__(None, None, None)

        elif kind == "topic_changed":
            await topic_banner(data)

        elif kind == "plan_created":
            step = cl.Step(name=f"วางแผน {len(data['steps'])} ขั้นตอน", type="llm")
            await step.__aenter__()
            step.output = plan_view(data)
            await step.__aexit__(None, None, None)

        elif kind == "step_started":
            step = cl.Step(name=f"[{data['step']}] {data['tool']}", type="tool")
            await step.__aenter__()
            step.input = json.dumps(data.get("arguments", {}), ensure_ascii=False, indent=2)
            steps[data["step"]] = step

        elif kind == "step_result":
            step = steps.get(data["step"])
            if step:
                if data["ok"]:
                    body = json.dumps(data["result"], ensure_ascii=False, indent=2)
                    step.output = (f"สำเร็จใน {data['duration_ms']} ms\n\n"
                                   f"```json\n{body[:2500]}\n```")
                else:
                    step.output = f"ไม่สำเร็จ: {data.get('error') or data.get('skipped_reason')}"
                await step.__aexit__(None, None, None)

        elif kind == "token":
            await answer.stream_token(data)

        elif kind == "usage":
            usage = data

        elif kind == "error":
            await cl.Message(content=f"เกิดข้อผิดพลาด: {data.get('error')}").send()

    await answer.send()
    if usage:
        await cost_meter(usage)
