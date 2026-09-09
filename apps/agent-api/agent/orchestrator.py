"""Multi-agent routing (Module 6).

The single-planner design used by the main flow is the right default for this
dataset. This module exists to make the alternative concrete rather than
theoretical, and to let participants measure the difference themselves.

Pattern implemented: Orchestrator-Workers.
"""

from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field

# ==========================================
# ส่วนที่เพิ่มเข้ามาเพื่อให้รันไฟล์นี้ได้ตรงๆ
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import llm
# ==========================================

class Specialist(str, Enum):
    TICKETS = "tickets"      # PostgreSQL: what was reported
    TOPOLOGY = "topology"    # Neo4j: what connects to what
    LOGS = "logs"            # OpenSearch: what the equipment reported


class RoutingDecision(BaseModel):
    specialists: list[Specialist] = Field(
        description="Which specialists are needed. Choose the minimum."
    )
    reason: str
    sequential: bool = Field(
        description=(
            "True when a later specialist needs an earlier one's findings. "
            "False when they can work independently and be merged."
        )
    )

SPECIALIST_BRIEF = {
    Specialist.TICKETS: (
        "คุณดูแลข้อมูล ticket และการตั้งค่าอุปกรณ์ "
        "ตอบเฉพาะสิ่งที่ 'ถูกแจ้งเข้ามา' และ 'ถูกตั้งค่าไว้' "
        "ถ้าคำถามเกี่ยวกับพฤติกรรมจริงของอุปกรณ์ ให้บอกว่าเป็นหน้าที่ของ logs"
    ),
    Specialist.TOPOLOGY: (
        "คุณดูแลโครงสร้างการเชื่อมต่อ "
        "หน้าที่สำคัญที่สุดคือหาจุดร่วม upstream ของอุปกรณ์หลายตัว "
        "และจำไว้ว่า adjacency ข้ามพื้นที่ได้"
    ),
    Specialist.LOGS: (
        "คุณดูแล log ของอุปกรณ์และเอกสารปฏิบัติการ "
        "ก่อนสรุปว่าอะไรเป็นเหตุเสีย ต้องเช็คก่อนเสมอว่าเป็นงาน maintenance หรือไม่"
    ),
}

ROUTER_PROMPT = """\
Route a network operations question to the specialists that can answer it.

  tickets   trouble tickets, incident history, device configuration, circuits
  topology  physical connections, adjacencies, shared upstream devices
  logs      device syslog, event counts, health scoring, runbooks

Choose the minimum set. Set sequential=true only when one specialist genuinely
needs another's output first - for example, finding devices from tickets before
looking up what they share upstream.
"""

async def route(question: str, stats: llm.LLMStats | None = None,
                model: str | None = None) -> RoutingDecision:
    return await llm.complete_structured(
        [
            {"role": "system", "content": ROUTER_PROMPT},
            {"role": "user", "content": question},
        ],
        RoutingDecision, stats=stats, model=model,
    )

# ==========================================
# บล็อกทดสอบจำลอง (จะทำงานเมื่อรันไฟล์นี้ตรงๆ)
if __name__ == "__main__":
    import asyncio
    
    async def run_test():
        print("🚀 ทดสอบระบบ Orchestrator Router...")
        
        # ลองตั้งคำถามให้ Router ตัดสินใจ
        question = "ช่วยหาข้อมูลให้หน่อยว่า Ticket ของสาขา BKK มีแจ้งอุปกรณ์ตัวไหนเสียบ้าง แล้วเอาไปเช็ค Topology ซิว่ามันต่อกับ upstream ตัวไหน"
        print(f"\nคำถาม: {question}")
        print("-" * 40)
        
        decision = await route(question)
        
        print(f"✅ ผู้เชี่ยวชาญ (Specialists) ที่เลือกใช้งาน: {[s.value for s in decision.specialists]}")
        print(f"✅ ทำงานตามลำดับไหม (Sequential): {decision.sequential}")
        print(f"✅ เหตุผล (Reason): {decision.reason}")

    asyncio.run(run_test())