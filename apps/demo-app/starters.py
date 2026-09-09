"""Clickable example questions for the demo UI.

Ordered to match the demo script: simple first, cross-service second,
out-of-scope third. A presenter can work straight down the list.
"""

from __future__ import annotations

DEMO_STARTERS = [
    {
        "label": "1. ticket ที่ยังไม่ปิด",
        "message": "ticket ที่ยังไม่ปิดตอนนี้มีอะไรบ้าง เรียงตามความรุนแรง",
        "note": "แหล่งเดียว - เริ่มจากง่ายก่อน",
    },
    {
        "label": "2. หาสาเหตุร่วม",
        "message": "ทำไมช่วงสองสัปดาห์นี้ถึงมีลูกค้าแจ้งเน็ตหลุดซ้ำๆ หลายราย",
        "note": "ข้ามสามระบบ - ไฮไลต์ของการเดโม",
    },
    {
        "label": "3. คำถามนอกขอบเขต",
        "message": "ช่วยเขียนอีเมลลาพักร้อนให้หน่อย",
        "note": "ต้องไม่เรียก tool เลย",
    },
    {
        "label": "4. เหตุเสียจริงหรือ maintenance",
        "message": "log ที่ APE-BKK-05 เมื่อ 3 วันก่อนเป็นเหตุเสียจริง หรือเป็นงานที่แจ้งไว้",
        "note": "ต้องเช็ค ticket ก่อนสรุป",
    },
    {
        "label": "5. อุปกรณ์ที่ไม่มีจริง",
        "message": "สถานะของ PE-CNX-99 ตอนนี้เป็นยังไง",
        "note": "ต้องตอบว่าไม่พบ ไม่แต่งข้อมูล",
    },
    {
        "label": "6. ประเมินผลกระทบก่อนซ่อม",
        "message": "ถ้าจะปิด APE-NBI-03 เพื่อซ่อม จะกระทบลูกค้ากี่ราย ใครบ้าง",
        "note": "คำตอบระดับที่ผู้บริหารใช้ตัดสินใจได้",
    },
]
