import asyncio
import time
import sys
from pathlib import Path

# ชี้ Path ไปที่ agent-api
sys.path.insert(0, str(Path(__file__).resolve().parent / "apps" / "agent-api"))

from agent import planner, orchestrator, llm

async def main():
    # คำถาม Q21 จากไฟล์ L3-three-source.yaml
    q = "ทำไมช่วงสองสัปดาห์นี้ถึงมีลูกค้าแจ้งเน็ตหลุดซ้ำๆ หลายราย"
    
    print(f"📌 คำถามทดสอบ (Q21): {q}\n")
    print("=" * 60)

    # ==========================================
    # 1. ทดสอบแบบ Single-Planner (Planner เดี่ยว)
    # ==========================================
    print("🤖 1. แบบ Single-Planner (คิดแผนรวดเดียวจบ)")
    stats_planner = llm.LLMStats()
    start_t = time.time()
    
    try:
        # พยายามส่งตัวเก็บสถิติ (stats) เข้าไปนับ token
        plan = await planner.create_plan(q, stats=stats_planner)
    except TypeError:
        plan = await planner.create_plan(q)
        
    time_planner = time.time() - start_t
    
    print(f"✅ แผนที่ได้ ({len(plan.steps)} ขั้นตอน):")
    for i, step in enumerate(plan.steps):
        # ดึงคำอธิบายโดยเช็กทั้ง reason และ justification
        desc = getattr(step, 'reason', getattr(step, 'justification', 'ไม่มีคำอธิบาย'))
        print(f"   [{i+1}] {step.tool}: {desc}")
    print("-" * 60)


    # ==========================================
    # 2. ทดสอบแบบ Orchestrator (กระจายงานให้ Worker)
    # ==========================================
    print("👥 2. แบบ Orchestrator (เป็นหัวหน้าคอยแบ่งงาน)")
    stats_orch = llm.LLMStats()
    start_t = time.time()
    
    decision = await orchestrator.route(q, stats=stats_orch)
    
    time_orch = time.time() - start_t
    
    print(f"✅ แผนกที่ถูกเลือก (Specialists): {[s.value for s in decision.specialists]}")
    print(f"✅ ทำงานตามลำดับ (Sequential): {decision.sequential}")
    print("=" * 60)
    
    # ==========================================
    # สรุปตารางเปรียบเทียบ
    # ==========================================
    print("\n📊 สรุปผลสำหรับกรอกตาราง (Benchmark):")
    print(f"| วัดค่า                 | Planner เดี่ยว | Orchestrator |")
    print(f"|------------------------|----------------|--------------|")
    
    # ดึงค่า Token ออกมาอย่างปลอดภัย ถ้าไม่มีให้แสดงเป็น N/A
    planner_tokens = getattr(stats_planner, 'total_tokens', 'N/A')
    orch_tokens = getattr(stats_orch, 'total_tokens', 'N/A')
    
    print(f"| Token รวม              | {planner_tokens:<14} | {orch_tokens:<12} |")
    print(f"| เวลารวม                | {time_planner:<14.2f} | {time_orch:<12.2f} |")
    print(f"| วางแผนถูกไหม?          | {'ดูจาก Step ด้านบน' :<14} | {'ดูจากแผนกด้านบน' :<12} |")

if __name__ == "__main__":
    asyncio.run(main())