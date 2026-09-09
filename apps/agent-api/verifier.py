import re
from typing import List, Dict, Any

async def verify(answer: str, results: list) -> Dict[str, Any]:
    """
    ตรวจสอบว่าทุกข้ออ้างในคำตอบ (answer) มีหลักฐานจาก step results รองรับหรือไม่
    """
    supported_tickets = set()
    supported_devices = set()
    evidence_text = ""
    
    for step in results:
        text_content = getattr(step, "result_text", str(step))
        evidence_text += " " + text_content
        
        found_tickets = re.findall(r"TK-\d{2}-\d{5}", text_content)
        supported_tickets.update(found_tickets)
        
        found_devices = re.findall(r"[A-Z]{3}-[A-Z]{3}-\d{2}", text_content)
        supported_devices.update(found_devices)

    errors = []

    # 1. ตรวจสอบ Ticket ID
    mentioned_tickets = re.findall(r"TK-\d{2}-\d{5}", answer)
    for ticket in mentioned_tickets:
        if not supported_tickets or ticket not in supported_tickets:
            errors.append(f"พบ Ticket ที่ไม่มีในหลักฐาน: {ticket}")

    # 2. ตรวจสอบ Metrics / ตัวเลขเปอร์เซ็นต์
    percent_matches = re.findall(r"\d+%", answer)
    if "CPU" in answer or percent_matches:
        if "CPU" not in evidence_text and not any(m in evidence_text for m in percent_matches):
            errors.append("มีการอ้างอิงข้อมูล Metrics หรือเปอร์เซ็นต์ที่ไม่มีอยู่ในหลักฐาน")

    # 3. ตรวจสอบการบิดเบือนเหตุการณ์
    if "เหตุเสีย" in answer or "ร้ายแรง" in answer:
        if "maintenance" in evidence_text.lower() or "ซ่อมบำรุง" in evidence_text:
            if "เหตุเสีย" not in evidence_text and "เสีย" not in evidence_text:
                errors.append("บิดเบือนข้อเท็จจริง: ระบุว่าเป็นเหตุเสีย แต่หลักฐานระบุเป็น Maintenance")
        elif not evidence_text:  
            errors.append("อ้างอิงเหตุเสียโดยไม่มีหลักฐานสนับสนุน")

    is_grounded = len(errors) == 0
    
    return {
        "is_grounded": is_grounded,
        "errors": errors,
        "message": "ผ่านการตรวจสอบ Grounding" if is_grounded else f"พบข้อผิดพลาด: {', '.join(errors)}"
    }

# --- ส่วนทดสอบผ่าน PowerShell (Test Script) ---
if __name__ == "__main__":
    import asyncio
    
    async def test():
        print("กำลังทดสอบ Verifier (ทั้งเคสผิดและเคสถูก)...")
        
        # 1. เคสที่จงใจผิด (ควรติด Error / is_grounded = False)
        bad_case = "APE-BKK-05 เกิดเหตุเสียร้ายแรง มี ticket TK-99-99999 รายงานไว้ CPU สูงถึง 95%"
        res_bad = await verify(bad_case, [])
        print("ผลทดสอบเคสผิด:", res_bad)

        # 2. เคสที่ถูกต้อง (ควรผ่าน / is_grounded = True)
        class MockStep:
            result_text = "พบ Ticket TK-25-00123 สำหรับอุปกรณ์ APE-BKK-05 อยู่ในสถานะ maintenance ประจำสัปดาห์"
        
        good_case = "อุปกรณ์ APE-BKK-05 มี ticket TK-25-00123 รายงานไว้ อยู่ในสถานะ maintenance"
        res_good = await verify(good_case, [MockStep()])
        print("ผลทดสอบเคสถูก:", res_good)

    asyncio.run(test())