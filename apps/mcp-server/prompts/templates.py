"""MCP Prompts: reusable investigation templates.

Prompts are the least understood of the three MCP primitives. They are not
system prompts and not tools - they are named, parameterised message templates
that a client can offer to a user as a starting point.

Their real value here is encoding investigation ORDER. A junior engineer and a
language model make the same mistake: they look at the loudest signal first.
These templates impose the sequence an experienced engineer would follow.
"""

from __future__ import annotations


def register(mcp) -> None:

    @mcp.prompt(title="Diagnose repeated customer complaints")
    def diagnose_repeated_complaints(range: str = "last_14d") -> str:
        """Find the shared root cause behind several similar complaints."""
        return f"""ช่วยหาสาเหตุร่วมของ ticket ที่ลูกค้าแจ้งอาการคล้ายกันในช่วง {range}

กรุณาทำตามลำดับนี้ และห้ามข้ามขั้นตอน:

1. ค้นหา ticket ในช่วงเวลาดังกล่าวที่มีอาการใกล้เคียงกัน
2. ระบุอุปกรณ์ที่ ticket แต่ละใบเกี่ยวข้อง
3. ตรวจสอบใน topology ว่าอุปกรณ์เหล่านั้นมี upstream ร่วมกันหรือไม่
   (ขั้นนี้สำคัญที่สุด - ticket จะไม่มีทางเอ่ยถึงอุปกรณ์ upstream
    เพราะฝั่งลูกค้ามองไม่เห็น)
4. ถ้าพบอุปกรณ์ที่เป็นจุดร่วม ให้ตรวจ log ของอุปกรณ์นั้น
   เฉพาะช่วงเวลาที่ ticket ถูกเปิด
5. สรุปว่าอะไรคือสาเหตุ พร้อมระบุว่าข้อสรุปแต่ละข้อมาจากแหล่งใด

ถ้าหลักฐานไม่พอที่จะสรุปสาเหตุ ให้บอกว่ายังสรุปไม่ได้และขาดข้อมูลอะไร
อย่าเดา"""

    @mcp.prompt(title="Investigate an adjacency failure")
    def investigate_adjacency(device_id: str) -> str:
        """Work through why a routing adjacency will not establish."""
        return f"""ช่วยตรวจสอบว่าทำไม adjacency ของ {device_id} ถึงไม่ขึ้น

ลำดับการตรวจสอบ:

1. หา neighbor ของ {device_id} จาก topology และดูว่า adjacency ตัวไหนอยู่สถานะ Down
2. **ดึง config ของทั้งสองฝั่ง** - ฝั่งเดียวไม่มีทางบอกได้ว่าค่าไม่ตรงกัน
   และ neighbor อาจอยู่คนละพื้นที่ อย่าจำกัดการค้นหาไว้ที่พื้นที่เดียว
3. เปรียบเทียบค่าที่ต้องตรงกันทั้งสองฝั่ง โดยเฉพาะ MTU, IS-type และ area
4. ตรวจ log ของ {device_id} เพื่อยืนยันอาการ
5. ค้นหา runbook ที่เกี่ยวข้องเพื่อดูขั้นตอนแก้ไขมาตรฐาน

ตอบพร้อมระบุค่าที่ไม่ตรงกันให้ชัดเจนว่าฝั่งไหนเป็นเท่าไหร่"""

    @mcp.prompt(title="Assess maintenance impact")
    def assess_maintenance_impact(device_id: str) -> str:
        """Quantify who is affected before taking a device out of service."""
        return f"""ต้องการปิด {device_id} เพื่อซ่อมบำรุง ช่วยประเมินผลกระทบ

ต้องตอบให้ครบทุกข้อ:

1. อุปกรณ์อะไรบ้างที่อยู่ใต้ {device_id} และจะขาดการเชื่อมต่อไปด้วย
2. มีวงจรลูกค้าทั้งหมดกี่วงจรบนอุปกรณ์เหล่านั้น
3. แยกลูกค้าตามกลุ่ม Enterprise / SME / Government พร้อมจำนวน
4. มี ticket ที่ยังไม่ปิดของอุปกรณ์กลุ่มนี้อยู่หรือไม่
   (ถ้ามี ควรพิจารณาแก้ไปพร้อมกันในหน้าต่างงานเดียว)
5. ค้นหา runbook เรื่องขั้นตอนการแจ้งลูกค้าก่อนปิดซ่อม

สรุปเป็นข้อมูลที่ผู้บริหารใช้ตัดสินใจได้ทันที"""

    @mcp.prompt(title="Proactive health review")
    def proactive_health_review() -> str:
        """Find equipment degrading before anyone raises a ticket."""
        return """ช่วยตรวจหาอุปกรณ์ที่กำลังมีปัญหา แม้ยังไม่มีใครแจ้ง

สิ่งที่ต้องระวัง:
- **อุปกรณ์ที่ไม่มี ticket ไม่ได้แปลว่าสุขภาพดี** อุปกรณ์ที่เสื่อมเงียบ
  มักไม่มี ticket เลย เพราะอาการยังไม่ถึงระดับที่ลูกค้าสังเกตเห็น
- ให้น้ำหนักกับ **แนวโน้มที่เพิ่มขึ้น** มากกว่าจำนวน error สะสม

ลำดับการทำงาน:
1. คำนวณคะแนนสุขภาพของอุปกรณ์ทุกตัวและจัดอันดับ
2. สำหรับตัวที่คะแนนต่ำที่สุด ให้ดูรายละเอียด log ว่าเป็นอาการแบบไหน
3. ตรวจว่ามี ticket ของอุปกรณ์นั้นหรือไม่
4. ตรวจว่ามีลูกค้ากี่รายที่พึ่งพาอุปกรณ์นั้น เพื่อประเมินความเร่งด่วน
5. เสนอลำดับความสำคัญในการเข้าไปตรวจสอบ"""

    @mcp.prompt(title="Triage a log alert")
    def triage_log_alert(device_id: str, range: str = "last_24h") -> str:
        """Decide whether an alert is a real incident before escalating."""
        return f"""มีการแจ้งเตือน log ของ {device_id} ในช่วง {range}
ช่วยประเมินว่าเป็นเหตุเสียจริงหรือไม่

**ขั้นตอนแรกที่ห้ามข้าม**: ตรวจสอบก่อนว่ามี ticket ประเภท maintenance
ที่ครอบคลุมช่วงเวลานั้นหรือไม่ งานบำรุงรักษาที่มีการ reload อุปกรณ์
จะสร้าง log ที่หน้าตาเหมือนเหตุเสียร้ายแรงทุกประการ

ถ้าไม่ใช่งานตามแผน ให้ทำต่อ:
1. ดู log ในช่วงเวลานั้นว่าเป็นเหตุการณ์ประเภทไหน เกิดถี่แค่ไหน
2. ตรวจว่าอุปกรณ์นี้มีอะไรอยู่ใต้บ้าง เพื่อประเมินขอบเขตผลกระทบ
3. ตรวจว่ามีลูกค้าแจ้งเข้ามาแล้วหรือยัง
4. ค้นหา runbook ที่ตรงกับอาการ

สรุปเป็น: เป็นเหตุเสียจริงหรือไม่ / ความรุนแรง / ควรทำอะไรต่อ"""
