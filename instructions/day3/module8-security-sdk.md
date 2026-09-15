# Module 8 · ความปลอดภัยและการเลือก SDK

**10:45 – 11:35** · เป้าหมาย: ออกแบบ MCP Server ที่ปลอดภัยพอจะต่อกับฐานข้อมูลจริงขององค์กร

---

## 1. หลักการเดียวที่ต้องจำจากโมดูลนี้

> **Guardrail ที่เขียนไว้ใน prompt คือ "คำขอ"**
> **Guardrail ที่เขียนไว้ในโค้ดและสิทธิ์ คือ "กฎ"**

Prompt injection เอาชนะคำขอได้เสมอ แต่เอาชนะสิทธิ์ระดับฐานข้อมูลไม่ได้

---

## 2. ชั้นป้องกัน 5 ชั้น

```mermaid
flowchart TD
    Q["คำขอจากโมเดล"] --> L1{"1. Intent Gate<br/>(ฝั่ง Agent)"}
    L1 -->|ผ่าน| L2{"2. ตรวจรูปแบบคำสั่ง"}
    L2 -->|ผ่าน| L3{"3. สิทธิ์ฐานข้อมูล<br/>mcp_reader"}
    L3 -->|ผ่าน| L4["4. จำกัดผลลัพธ์<br/>cap_rows / timeout"]
    L4 --> L5["5. กรองความลับ<br/>redact"]
    L5 --> OK["ผลลัพธ์"]
    L1 -->|ไม่ผ่าน| AUD["Audit log<br/>+ ปฏิเสธ"]
    L2 -->|ไม่ผ่าน| AUD
    L3 -->|ไม่ผ่าน| AUD
    style L3 fill:#e0ffe0,stroke:#0a0
```

**ชั้นที่ 3 คือชั้นเดียวที่ prompt injection ชนะไม่ได้ไม่ว่าจะเก่งแค่ไหน**

### Permission Layer — ทำที่ฐานข้อมูล

`docker/postgres/init/99_readonly_role.sql`:

```sql
-- CREATE ROLE mcp_reader LOGIN PASSWORD '...';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_reader;
REVOKE CREATE ON SCHEMA public FROM mcp_reader;
ALTER ROLE mcp_reader SET statement_timeout = '15s';
```

**ลองด้วยตัวเองที่ pgAdmin** — ล็อกอินด้วย `mcp_reader` แล้วรัน:

```sql
UPDATE tickets SET severity = 'low';
```

จะถูกปฏิเสธที่ระดับฐานข้อมูล ไม่ว่าโมเดลจะถูกหลอกด้วยวิธีไหนก็ตาม

### Sandboxing — Tool ที่อันตราย

| ความเสี่ยง | วิธีคุม |
|---|---|
| รันสคริปต์ตามใจ | **Allowlist เท่านั้น** — `ALLOWED_SCRIPTS` ใน `apps/agent-api/tools/reports.py` |
| ประกอบ command line | ใช้ `subprocess.run(argv, shell=False)` ห้าม `shell=True` |
| สคริปต์ค้าง | `timeout=30` |
| output ท่วม | `MAX_OUTPUT_CHARS` |
| อ่านไฟล์นอกขอบเขต | `safe_path()` resolve แล้วเทียบว่าอยู่ใต้ root จริง |

> **"ชื่อสคริปต์" ต้องเป็นชุดปิดที่นักพัฒนากำหนด ไม่ใช่ string ที่โมเดลส่งมา**

### Secrets

```mermaid
flowchart LR
    ENV[".env<br/>บนเครื่อง server"] --> SRV["MCP Server"]
    SRV -->|"ผลลัพธ์ที่ผ่าน redact แล้ว"| CLI["MCP Client"]
    SRV -.->|"ห้ามส่งออกเด็ดขาด"| X["credential"]
    style X fill:#ffe0e0,stroke:#c00
```

`redact()` ทำงานกับ **ทุกข้อความที่ออกจาก tool** รวมถึงข้อมูลที่ดึงจากฐานข้อมูล เพราะ config snippet อาจมี SNMP community string ปนอยู่

---

## 3. Audit Log

ทุกครั้งที่ปฏิเสธหรือตัดผลลัพธ์ ต้องบันทึก

คัดลอกทับบรรทัดสุดท้ายแทนโค้ดชุดนี้ หลังจากเสร็จแล้วลองรัน cat audit.log apps/agent-api/main.py
```
if __name__ == "__main__":
    import os

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("AGENT_API_PORT", "8080")))
```
```python
import datetime
from mcp.server.fastmcp import FastMCP
from tools.reports import get_safe_path

mcp = FastMCP("MySimpleServer")

# 1. สร้าง Class แบบง่าย เพื่อให้ใช้ syntax .emit() ได้
class AuditEvent:
    def __init__(self, tool: str, decision: str, reason: str, detail: str = ""):
        self.tool = tool
        self.decision = decision
        self.reason = reason
        self.detail = detail

    def emit(self):
        """เขียนข้อมูลลงไฟล์ audit.log"""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{now}] {self.decision.upper()} | Tool: {self.tool} | Reason: {self.reason} | Detail: {self.detail}\n"
        
        with open("audit.log", "a", encoding="utf-8") as f:
            f.write(log_entry)

# 2. นำไปใช้งานดัก Error แบบรวมศูนย์
@mcp.tool()
def read_report(filename: str) -> str:
    """ดึงข้อมูลรายงาน"""
    try:
        # ลองตรวจ Path
        safe_path = get_safe_path(filename)
        return f"✅ อ่านไฟล์ {filename} สำเร็จ"

    except Exception as e:
        # ดักทุก Error แล้วใช้ Syntax ที่คุณต้องการ
        AuditEvent(
            tool="read_report", 
            decision="blocked", 
            reason=type(e).__name__, # ดึงชื่อ Error มาเป็น Reason อัตโนมัติ (เช่น ValueError)
            detail=str(e)
        ).emit()
        
        # ตอบกลับ LLM ด้วยประโยคเดียวสั้นๆ
        return "❌ คำขอถูกปฏิเสธ: ไม่สามารถเข้าถึงไฟล์ที่ระบุได้"

# ==========================================
# 3. จุดสั่งรันเซิร์ฟเวอร์
# ==========================================
if __name__ == "__main__":
    print("🚀 เริ่มการทดสอบระบบป้องกัน (Simulated LLM Requests)\n")

    # สถานการณ์ที่ 1: AI ขออ่านไฟล์ปกติที่อนุญาต
    print("📝 [Test 1] AI สั่งอ่าน: 'q1_summary.csv'")
    print(">> ตอบกลับ AI:", read_report("q1_summary.csv"))
    print("-" * 50)

    # สถานการณ์ที่ 2: AI โดน Prompt Injection สั่งให้อ่านไฟล์ลับนอก Allowlist
    print("🕵️‍♂️ [Test 2] AI สั่งอ่าน: 'secret_budget.xlsx'")
    print(">> ตอบกลับ AI:", read_report("secret_budget.xlsx"))
    print("-" * 50)

    # สถานการณ์ที่ 3: AI โดนแฮ็กเกอร์สั่งเจาะระบบด้วย Path Traversal
    print("💀 [Test 3] AI สั่งอ่าน: '../etc/passwd'")
    print(">> ตอบกลับ AI:", read_report("../etc/passwd"))
    print("-" * 50)

    print("\n✅ ทดสอบเสร็จสิ้น! ตอนนี้ลองเปิดดูไฟล์ 'audit.log' ในโฟลเดอร์ดูครับ")
```

**และข้อความปฏิเสธที่ส่งกลับต้องไม่เผยโครงสร้างภายใน** — บอกว่าถูกปฏิเสธเพราะอะไรในระดับที่ผู้ใช้เข้าใจ แต่ไม่บอกชื่อตาราง ชื่อ role หรือ path

---

## 4. เลือก SDK: Python หรือ TypeScript

| | Python SDK | TypeScript SDK |
|---|---|---|
| เหมาะกับ | ทีม data/backend, งาน ML | ทีม frontend, deploy บน edge |
| ระบบนิเวศฐานข้อมูล | ครบมาก | ครบพอใช้ |
| deploy แบบ serverless | ทำได้ | **ทำได้ดีกว่า** |
| ในโครงการนี้ | **เลือกตัวนี้** | — |

**เหตุผลที่เลือก Python**: ฐานข้อมูลทั้ง 3 ตัวมี driver ที่โตเต็มที่ · ทีมที่ดูแล MPLS LLM ใช้ Python อยู่แล้ว · โค้ดวันที่ 1-2 เป็น Python ทั้งหมด ต่อกันได้ทันที

รายละเอียดเปรียบเทียบพร้อมโค้ดตัวอย่างสองภาษา: [reference/sdk-comparison.md](../reference/sdk-comparison.md)

### FastMCP หรือ SDK ดิบ

โปรเจกต์นี้ใช้ `FastMCP` (อยู่ใน official SDK) เพราะประกาศ tool ด้วย decorator ได้เลย ทำให้เห็น **สิ่งที่สอน** ไม่ใช่ boilerplate

 นำ Code ชุดนี้ไปทับส่วนของ if __name__ == "__main__":
```python
@mcp.tool(annotations={"readOnlyHint": True})
def search_tickets(status: str | None = None, range: str = "last_30d") -> dict:
    """
    ใช้ค้นหาข้อมูล Ticket ปัญหาการใช้งานของระบบ
    - status: สถานะของทิกเก็ต (เช่น 'open', 'closed') หากไม่ระบุจะค้นหาทั้งหมด
    - range: ช่วงเวลาที่ต้องการค้นหา (เช่น 'last_30d', 'last_7d')
    """
    # ในระบบจริง ตรงนี้จะใช้คำสั่ง SQL วิ่งไปดึงข้อมูลจาก Database 
    # (ซึ่งจะถูกคุมด้วยสิทธิ์ mcp_reader อีกชั้นนึง)
    
    # สำหรับการทดสอบ เราจะคืนค่าจำลอง (Mock Data) กลับไปให้ AI ก่อน
    return {
        "status": "success",
        "search_params": {"status": status, "range": range},
        "data": [
            {"id": "TCK-101", "severity": "high", "status": "open", "issue": "Router Down"},
            {"id": "TCK-102", "severity": "low", "status": "closed", "issue": "VPN Login Failed"}
        ]
    }
# ==========================================
# 3. จุดสั่งรันเซิร์ฟเวอร์
# ==========================================
# ==========================================
# 3. จุดทดสอบแบบรันจบในตัว (Simulated LLM Requests)
# ==========================================
if __name__ == "__main__":
    print("🚀 เริ่มการทดสอบระบบป้องกัน (Simulated LLM Requests)\n")

    print("📝 [Test 1] AI สั่งอ่าน: 'q1_summary.csv'")
    print(">> ตอบกลับ AI:", read_report("q1_summary.csv"))
    print("-" * 50)

    print("🕵️‍♂️ [Test 2] AI สั่งอ่าน: 'secret_budget.xlsx'")
    print(">> ตอบกลับ AI:", read_report("secret_budget.xlsx"))
    print("-" * 50)

    print("💀 [Test 3] AI สั่งอ่าน: '../etc/passwd'")
    print(">> ตอบกลับ AI:", read_report("../etc/passwd"))
    print("-" * 50)

    # เพิ่ม Test 4 สำหรับทดสอบ Tool ใหม่
    print("🎫 [Test 4] AI สั่งค้นหาทิกเก็ต: status='open', range='last_7d'")
    print(">> ตอบกลับ AI:", search_tickets(status="open", range="last_7d"))
    print("-" * 50)

    print("\n✅ ทดสอบเสร็จสิ้น! ตอนนี้ระบบมี 2 Tools พร้อมให้บริการแล้ว")
```

type hint กลายเป็น `inputSchema` และ docstring กลายเป็น `description` โดยอัตโนมัติ

---
นำ Code ชุดนี้ไปแทน Code ที่ทำมาข้างต้นทั้งหมด เพิ่มระบบกรองข้อมูลความลับ (Redaction) ที่ต้องทำหน้าที่เซ็นเซอร์ข้อมูล (เช่น SNMP community string หรือ Password) ก่อนที่ข้อความจะหลุดออกไปหา LLM
```python
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


# ==========================================
# จุดทดสอบแบบรันจบในตัว (จำลองการทำงานของ AI)
# ==========================================
if __name__ == "__main__":
    import datetime
    import json
    from mcp.server.fastmcp import FastMCP
    from tools.reports import get_safe_path

    mcp = FastMCP("MySecureServer")

    class AuditEvent:
        def __init__(self, tool: str, decision: str, reason: str, detail: str = ""):
            self.tool = tool
            self.decision = decision
            self.reason = reason
            self.detail = detail

        def emit(self):
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{now}] {self.decision.upper()} | Tool: {self.tool} | Reason: {self.reason} | Detail: {self.detail}\n"
            with open("audit.log", "a", encoding="utf-8") as f:
                f.write(log_entry)

    def redact(data):
        secrets = [
            "public_snmp_read", 
            "superadmin_pass", 
            "192.168.1.100"
        ]
        is_dict = isinstance(data, dict)
        text_data = json.dumps(data, ensure_ascii=False) if is_dict else str(data)
            
        for secret in secrets:
            text_data = text_data.replace(secret, "████████")
            
        return json.loads(text_data) if is_dict else text_data

    @mcp.tool()
    def read_report(filename: str) -> str:
        try:
            safe_path = get_safe_path(filename)
            raw_content = f"✅ อ่านไฟล์ {filename} สำเร็จ ค่าคอนฟิกคือ superadmin_pass"
            return redact(raw_content)
        except Exception as e:
            AuditEvent(
                tool="read_report", 
                decision="blocked", 
                reason=type(e).__name__,
                detail=str(e)
            ).emit()
            return "❌ คำขอถูกปฏิเสธ: ไม่สามารถเข้าถึงไฟล์ที่ระบุได้"

    @mcp.tool(annotations={"readOnlyHint": True})
    def search_tickets(status: str | None = None, range: str = "last_30d") -> dict:
        raw_data = {
            "status": "success",
            "data": [
                {"id": "TCK-101", "issue": "Router Down", "config_snippet": "snmp-server community public_snmp_read RO"},
                {"id": "TCK-102", "issue": "DB Login Failed", "error_log": "Failed password for superadmin_pass from 192.168.1.100"}
            ]
        }
        return redact(raw_data)

    print("🚀 เริ่มการทดสอบระบบป้องกันและเซ็นเซอร์ข้อมูล\n")

    print("📝 [Test 1] AI สั่งอ่าน: 'q1_summary.csv'")
    print(">> ตอบกลับ AI:", read_report("q1_summary.csv"))
    print("-" * 50)

    print("🕵️‍♂️ [Test 2] AI สั่งอ่าน: 'secret_budget.xlsx'")
    print(">> ตอบกลับ AI:", read_report("secret_budget.xlsx"))
    print("-" * 50)

    print("💀 [Test 3] AI สั่งอ่าน: '../etc/passwd'")
    print(">> ตอบกลับ AI:", read_report("../etc/passwd"))
    print("-" * 50)

    print("🎫 [Test 4] AI สั่งค้นหาทิกเก็ต: status='open', range='last_7d'")
    print(">> ตอบกลับ AI:", json.dumps(search_tickets(status="open", range="last_7d"), indent=2))
    print("-" * 50)

    print("\n✅ ทดสอบเสร็จสิ้น! เช็คผลการเซ็นเซอร์ (████████) ใน Test 4 ได้เลย")
```
---
## 5. OAuth 2.1 — รู้ไว้ แต่ยังไม่ใช้

spec รุ่นใหม่กำหนดให้ MCP server ที่เปิดบนเครือข่ายทำตัวเป็น OAuth Resource Server

โปรเจกต์นี้ **ไม่ทำ** เพราะอยู่ใน internal network และเป้าหมายคือสอน MCP ไม่ใช่สอน OAuth

**แต่ต้องรู้ว่าเมื่อขึ้น production จริงต้องมี** โดยเฉพาะเมื่อ NEX จะเรียกใช้ผ่านเครือข่ายองค์กร

---

## 6. เช็คลิสต์ก่อนเปิด MCP Server ให้ระบบจริง

- [ ] บัญชีฐานข้อมูลเป็น read-only จริง (ทดสอบด้วยการลอง UPDATE)
- [ ] มี statement timeout
- [ ] จำกัดจำนวนแถวและขนาด output
- [ ] tool ที่รันสคริปต์ใช้ allowlist ไม่ใช่ string จากโมเดล
- [ ] path ทุกเส้นถูก resolve และตรวจว่าอยู่ในขอบเขต
- [ ] มี redact ครอบทุก output
- [ ] มี audit log ทุกการปฏิเสธ
- [ ] secrets อยู่ในตัวแปรสภาพแวดล้อม ไม่อยู่ในโค้ด
- [ ] ประกาศ `readOnlyHint` / `destructiveHint` ให้ครบ
- [ ] มี auth เมื่อเปิดบนเครือข่าย

---

## 7. ต่อไป

→ [โจทย์ที่ 5: Guardrail Red-team](challenge5-guardrail-redteam.md)
