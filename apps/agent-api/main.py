#!/usr/bin/env python3
"""Agent API.

Wraps the agent as an HTTP service so any frontend can drive it - Chainlit
during the workshop, and a real NMS integration afterwards. The important
design choice is that the API streams EVENTS, not just text: the caller sees
the intent decision, the plan, and each tool call as they happen.

That is what lets the UI show the agent thinking instead of a spinner, and it
is what makes a demo persuasive rather than magical.

Run:
    make api          -> http://localhost:8080/docs
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from schemas import ChatRequest, IntentLabel  # noqa: E402
from verifier import verify

from agent import (  # noqa: E402
    events,
    grounding,
    intent,
    llm,
    mcp_client,
    memory,
    planner,
    synthesizer,
)
from agent.events import EventType  # noqa: E402

app = FastAPI(
    title="NT IP-MPLS Agent API",
    description="AI agent for network operations, backed by an MCP server.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # workshop only; restrict this in production
    allow_methods=["*"],
    allow_headers=["*"],
)


async def run_turn(request: ChatRequest):
    """One conversational turn, emitted as a stream of events.

    The order below is the agent's control flow, and it is deliberate:
    intent before memory, memory before planning, planning before any tool
    call, and grounding after the answer but before it is considered final.
    """
    session = memory.get(request.session_id)
    session.turn += 1
    stats = llm.LLMStats()
    tool_calls = 0

    try:
        # ---------- 1. Intent ----------
        history = session.build_context()
        decision = await intent.classify(
            request.message, history=history, stats=stats, model=request.model
        )
        yield events.sse(EventType.INTENT_CHECKED, decision.model_dump())

        # Refusals and clarifications end the turn without touching any tool.
        if decision.label in (IntentLabel.OUT_OF_SCOPE, IntentLabel.NEEDS_CLARIFICATION):
            text = intent.refusal_message(decision)
            for chunk in text.split(" "):
                yield events.sse(EventType.TOKEN, chunk + " ")
            # An out-of-scope aside must NOT disturb the current topic. The
            # user interrupted themselves; they did not change the subject.
            yield events.sse(EventType.USAGE,
                             {**stats.as_dict(), "tool_calls": 0,
                              "context_tokens": session.context_tokens()})
            yield events.sse(EventType.DONE, {"reason": decision.label.value})
            return

        # ---------- 2. Memory ----------
        changed, why = session.detect_topic_shift(request.message)
        if changed:
            before = session.context_tokens()
            await session.start_topic(request.message, stats=stats)
            yield events.sse(EventType.TOPIC_CHANGED, {
                "reason": why,
                "new_topic": session.topic.model_dump() if session.topic else None,
                "context_tokens_before": before,
                "context_tokens_after": session.context_tokens(),
                "archived_summaries": session.archived[-3:],
            })
        session.add_turn("user", request.message)
        yield events.sse(EventType.MEMORY_UPDATED, {
            "turn": session.turn,
            "topic": session.topic.label if session.topic else None,
            "context_tokens": session.context_tokens(),
            "archived_count": len(session.archived),
        })

        # ---------- General knowledge: answer, no tools ----------
        if decision.label == IntentLabel.GENERAL_KNOWLEDGE:
            answer = ""
            async for token in synthesizer.answer_general(
                request.message, context=session.build_context(),
                stats=stats, model=request.model
            ):
                answer += token
                yield events.sse(EventType.TOKEN, token)
            session.add_turn("assistant", answer)
            yield events.sse(EventType.USAGE,
                             {**stats.as_dict(), "tool_calls": 0,
                              "context_tokens": session.context_tokens()})
            yield events.sse(EventType.DONE, {"reason": "general_knowledge"})
            return

        # ---------- 3. Plan ----------
        plan = await planner.create_plan(
            request.message, context=session.build_context(),
            stats=stats, model=request.model,
        )
        yield events.sse(EventType.PLAN_CREATED, plan.model_dump())

        # ---------- 4. Execute ----------
        from agent import executor  # imported here to keep startup fast

        results = []
        async for event_type, payload in executor.execute(plan):
            if event_type == EventType.STEP_RESULT:
                tool_calls += 1
                from schemas import StepResult

                results.append(StepResult(**payload))
            yield events.sse(event_type, payload)

        # ---------- 5. Synthesise ----------
        answer = ""
        async for token in synthesizer.synthesize_stream(
            request.message, plan, results,
            context=session.build_context(), stats=stats, model=request.model,
        ):
            answer += token
            yield events.sse(EventType.TOKEN, token)

        session.add_turn("assistant", answer)

        # ---------- 6. Ground ----------
        try:
            # เรียกใช้ฟังก์ชัน verify จาก verifier.py ที่เราสร้างขึ้น
            verdict = await verify(answer, results)
            yield events.sse(EventType.GROUNDING_CHECKED, verdict)
        except Exception as exc:  # noqa: BLE001 - never fail a turn on the check
            yield events.sse(EventType.GROUNDING_CHECKED,
                             {"is_grounded": None, "error": str(exc)})

        yield events.sse(EventType.USAGE, {
            **stats.as_dict(),
            "tool_calls": tool_calls,
            "context_tokens": session.context_tokens(),
        })
        yield events.sse(EventType.DONE, {"reason": "complete"})

    except Exception as exc:  # noqa: BLE001
        yield events.sse(EventType.ERROR,
                         {"error": f"{type(exc).__name__}: {exc}"})
        yield events.sse(EventType.DONE, {"reason": "error"})


@app.post("/chat", summary="Ask a question, receive a stream of events")
async def chat(request: ChatRequest):
    return StreamingResponse(
        run_turn(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health", summary="Liveness and dependency check")
async def health():
    status: dict = {"api": "ok"}
    try:
        tools = await mcp_client.get().list_tools()
        status["mcp"] = {"ok": True, "tool_count": len(tools)}
    except Exception as exc:  # noqa: BLE001
        status["mcp"] = {"ok": False, "error": str(exc)}
    try:
        from agent import clock_probe  # noqa: F401
    except ImportError:
        pass
    return status


@app.get("/sessions/{session_id}/memory",
         summary="Inspect what the agent currently remembers")
async def get_memory(session_id: str):
    """Exposed on purpose.

    Memory management is invisible from the outside, which makes it impossible
    to learn from and impossible to debug. Challenge 4 asks participants to dump
    this after every turn and plot how context size changes - the plot is the
    proof that topic shift detection is working.
    """
    session = memory.get(session_id)
    return session.snapshot().model_dump()


@app.delete("/sessions/{session_id}", summary="Clear a session")
async def clear_session(session_id: str):
    memory.reset(session_id)
    return {"ok": True, "session_id": session_id}


@app.get("/tools", summary="List the tools exposed by the MCP server")
async def list_tools():
    try:
        return {"tools": await mcp_client.get().list_tools()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/resources", summary="List MCP resources")
async def list_resources():
    try:
        return {"resources": await mcp_client.get().list_resources()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


if __name__ == "__main__":
    import os

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("AGENT_API_PORT", "8080")))
