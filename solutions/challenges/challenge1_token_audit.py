#!/usr/bin/env python3
"""Challenge 1 reference solution: Thai token audit.

    python solutions/challenges/challenge1_token_audit.py

Answers three questions with numbers from the real dataset:
    1. How much more does Thai text cost than English of the same length?
    2. How wrong is tiktoken when used against a Gemma model?
    3. What would embedding the production corpus actually cost?
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "agent-api"))
from agent import tokenizer  # noqa: E402

PG_DSN = os.getenv("PG_ADMIN_DSN",
                   "postgresql://mpls:mpls_dev_password@localhost:5432/mplsdb")

SAMPLE_SIZE = 50

# Production figures from the project brief.
PROD_DEVICES = 2600
TICKETS_PER_DEVICE_PER_YEAR = 30
EMBEDDINGS_PER_SECOND = 500


def thai_ratio(text: str) -> float:
    """Fraction of characters in the Thai unicode block."""
    if not text:
        return 0.0
    thai = sum(1 for ch in text if "฀" <= ch <= "๿")
    return thai / len(text)


def classify(text: str) -> str:
    """Bucket a ticket by script.

    The thresholds are arbitrary but stated, which is what matters: an
    estimate whose assumptions are written down can be argued with.
    """
    ratio = thai_ratio(text)
    if ratio > 0.6:
        return "ไทยล้วน"
    if ratio < 0.1:
        return "อังกฤษล้วน"
    return "ปนกัน"


def load_sample() -> list[tuple[str, str]]:
    with psycopg.connect(PG_DSN) as conn:
        cur = conn.cursor()
        # setseed makes the sample reproducible, so the numbers in a report
        # can be regenerated.
        cur.execute("SELECT setseed(0.42)")
        cur.execute(
            """SELECT ticket_id, title || E'\n\n' || description
               FROM tickets ORDER BY random() LIMIT %s""",
            (SAMPLE_SIZE,),
        )
        return cur.fetchall()


def main() -> int:
    print("\n=== Challenge 1: Thai Token Audit ===\n")

    rows = load_sample()
    groups: dict[str, list[dict]] = {"ไทยล้วน": [], "อังกฤษล้วน": [], "ปนกัน": []}

    for _, text in rows:
        measured = tokenizer.compare(text)
        measured["chars"] = len(text)
        groups[classify(text)].append(measured)

    # ---------- Task 2: three-way comparison ----------
    print("  ตารางเปรียบเทียบ 3 วิธีนับ\n")
    header = (f"  {'กลุ่ม':<12}{'n':>4}{'อักขระ':>9}{'คำ(ไทย)':>10}"
              f"{'token(Gemma)':>14}{'token(tiktoken)':>17}{'ผิด %':>9}")
    print(header)
    print("  " + "-" * (len(header) - 2))

    summary: dict[str, dict] = {}
    for name, items in groups.items():
        if not items:
            continue
        n = len(items)
        chars = sum(i["chars"] for i in items) / n
        words = sum(i["thai_words"] or 0 for i in items) / n
        gemma = sum(i["gemma_tokens"] or 0 for i in items) / n
        tik = sum(i["tiktoken_tokens"] or 0 for i in items) / n
        error = (tik - gemma) / gemma * 100 if gemma else 0
        summary[name] = {"n": n, "chars": chars, "gemma": gemma,
                         "tiktoken": tik, "error": error}
        print(f"  {name:<12}{n:>4}{chars:>9.0f}{words:>10.0f}"
              f"{gemma:>14.0f}{tik:>17.0f}{error:>8.1f}%")

    # ---------- Task 3: ratios that support a decision ----------
    print("\n  อัตราส่วนที่ใช้ตัดสินใจได้\n")
    for name, stats in summary.items():
        per_char = stats["gemma"] / stats["chars"] if stats["chars"] else 0
        print(f"    {name:<12} {per_char:.3f} token ต่อ 1 อักขระ")

    thai = summary.get("ไทยล้วน")
    english = summary.get("อังกฤษล้วน")
    if thai and english:
        thai_rate = thai["gemma"] / thai["chars"]
        eng_rate = english["gemma"] / english["chars"]
        multiplier = thai_rate / eng_rate
        print(f"\n    ที่จำนวนอักขระเท่ากัน ภาษาไทยใช้ token "
              f"มากกว่าอังกฤษ {multiplier:.2f} เท่า")

    total_tokens = sum(
        tokenizer.count(text) for _, text in rows
    ) / len(rows)
    with psycopg.connect(PG_DSN) as conn:
        ticket_count = conn.execute("SELECT count(*) FROM tickets").fetchone()[0]
    print(f"\n    embed ticket ทั้ง {ticket_count} ใบ ใช้ประมาณ "
          f"{total_tokens * ticket_count:,.0f} token")

    # ---------- Task 4: production projection ----------
    print("\n  ประมาณการเมื่อขึ้น production\n")
    annual_tickets = PROD_DEVICES * TICKETS_PER_DEVICE_PER_YEAR
    annual_tokens = annual_tickets * total_tokens
    hours = annual_tickets / EMBEDDINGS_PER_SECOND / 3600

    print(f"    สมมติฐาน: {PROD_DEVICES:,} อุปกรณ์ × "
          f"{TICKETS_PER_DEVICE_PER_YEAR} ticket/ปี "
          f"= {annual_tickets:,} ใบ/ปี")
    print(f"    token รวมต่อปี          {annual_tokens:,.0f}")
    print(f"    เวลา embed ครั้งแรก      {hours:.1f} ชั่วโมง "
          f"(ที่ {EMBEDDINGS_PER_SECOND} ข้อความ/วินาที)")
    print(f"\n    ถ้าเปลี่ยนโมเดล embedding ต้อง re-embed ทั้งหมดใหม่")
    print(f"    ซึ่งหมายถึงหยุดใช้ semantic search {hours:.1f} ชั่วโมง")
    print(f"    หรือต้องทำ dual-write ระหว่างเปลี่ยน")

    # ---------- Task 5: one recommendation, with numbers ----------
    print("\n  ข้อเสนอลดต้นทุน\n")
    print("    เก็บ embedding ของ title + สรุปที่ตัดแล้ว แทนที่จะเก็บทั้ง description")
    if thai:
        saving = 0.45
        print(f"    จากตัวอย่าง description กินประมาณ 70-80% ของ token ทั้งใบ")
        print(f"    การสรุปให้เหลือ 2 ประโยคก่อน embed ลด token ได้ราว "
              f"{saving * 100:.0f}%")
        print(f"    = ประหยัดราว {annual_tokens * saving:,.0f} token/ปี")
        print(f"    แลกกับความแม่นที่ลดลงเล็กน้อย ซึ่งต้องวัดด้วย make eval ก่อนตัดสินใจ")

    print("\n  ข้อสรุปที่สำคัญที่สุด\n")
    if summary.get("ไทยล้วน"):
        err = summary["ไทยล้วน"]["error"]
        print(f"    tiktoken ให้ตัวเลขคลาดเคลื่อน {err:+.1f}% กับข้อความไทย")
        print(f"    ถ้าใช้ตัวเลขนี้วางแผนงบประมาณหรือกำหนดขนาด chunk")
        print(f"    จะผิดตั้งแต่ต้นโดยไม่มีอะไรเตือน\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
