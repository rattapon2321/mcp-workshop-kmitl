"""Seed the time-dependent half of PostgreSQL.

Static reference data (sites, devices, interfaces, configs) lives in
docker/postgres/init/*.sql where participants can read it as plain SQL.
Everything with a timestamp is generated here instead, so it stays relative
to the seeding run rather than frozen to a calendar date.
"""

from __future__ import annotations

import os

import psycopg
from common import ACCESS_DEVICES, DEVICE_BY_ID, hours_ago, rng, step

import embed

CUSTOMER_NAMES = [
    ("บริษัท สยามเทคโนโลยี จำกัด", "Enterprise"),
    ("โรงพยาบาลนนท์เวชการ", "Enterprise"),
    ("บริษัท ไทยโลจิสติกส์ เอ็กซ์เพรส", "Enterprise"),
    ("สำนักงานเขตพื้นที่การศึกษานนทบุรี", "Government"),
    ("เทศบาลนครนนทบุรี", "Government"),
    ("การประปาส่วนภูมิภาค สาขานนทบุรี", "Government"),
    ("ร้านกาแฟ Bean & Byte", "SME"),
    ("คลินิกทันตกรรมสไมล์", "SME"),
    ("บริษัท เอ็นบีไอ พริ้นติ้ง จำกัด", "SME"),
    ("ห้างหุ้นส่วน รุ่งเรืองการช่าง", "SME"),
    ("บริษัท กรุงเทพ ดาต้าเซ็นเตอร์ จำกัด", "Enterprise"),
    ("ธนาคารออมทรัพย์ประชาชน สาขาบางกระสอ", "Enterprise"),
    ("บริษัท ทรัพย์เจริญ พร็อพเพอร์ตี้", "SME"),
    ("โรงเรียนนนทบุรีวิทยา", "Government"),
    ("บริษัท มีเดีย สตูดิโอ 88", "SME"),
    ("ศูนย์ราชการจังหวัดนนทบุรี", "Government"),
    ("บริษัท ฟู้ดเซอร์วิส เซ็นทรัล", "Enterprise"),
    ("ร้านสะดวกซื้อ ควิกช็อป สาขา 12", "SME"),
    ("บริษัท ออโต้พาร์ท อินดัสทรี", "Enterprise"),
    ("คลินิกกายภาพบำบัดบ้านสุขใจ", "SME"),
    ("บริษัท ซอฟต์แวร์เฮ้าส์ ไทยแลนด์", "SME"),
    ("สหกรณ์ออมทรัพย์ครูนนทบุรี", "Government"),
    ("บริษัท พลาสติกไทย จำกัด", "Enterprise"),
    ("ร้านหนังสือ อ่านเพลิน", "SME"),
    ("บริษัท เอเชีย เทรดดิ้ง กรุ๊ป", "Enterprise"),
    ("สถานีตำรวจภูธรเมืองนนทบุรี", "Government"),
    ("บริษัท กรีนเอเนอร์จี โซลูชั่น", "SME"),
    ("โรงแรมริเวอร์ไซด์ นนทบุรี", "Enterprise"),
    ("บริษัท เมดิคอล ซัพพลาย", "SME"),
    ("ศูนย์กีฬาเทศบาลนนทบุรี", "Government"),
]

SERVICE_TYPES = ["MPLS-VPN", "Internet", "Leased Line"]

FILLER_TITLES = {
    "link_down": [
        "วงจรล่ม ใช้งานไม่ได้ทั้งสาขา",
        "ลิงก์ down ตั้งแต่เช้า",
        "circuit ไม่ทำงาน ping ไม่ผ่าน",
    ],
    "slow": [
        "ความเร็วไม่เต็มตามแพ็กเกจ",
        "latency สูงผิดปกติช่วงเย็น",
        "โหลดไฟล์ช้ากว่าปกติมาก",
    ],
    "inquiry": [
        "ขอทราบ bandwidth ปัจจุบันของวงจร",
        "สอบถามขั้นตอนการย้ายจุดติดตั้ง",
        "ขอใบรับรองการให้บริการ",
        "สอบถามค่าบริการเพิ่มความเร็ว",
    ],
    "config": [
        "ขอเปลี่ยน IP address ของวงจร",
        "ตั้งค่า VLAN ไม่ตรงกับที่แจ้ง",
        "ขอเพิ่ม route ปลายทางใหม่",
    ],
    "maintenance": [
        "แผนงานบำรุงรักษาประจำไตรมาส",
        "แจ้งดับไฟฟ้าเพื่อปรับปรุงระบบ",
        "งานเปลี่ยนสายไฟเบอร์ช่วงถนนหลัก",
    ],
}


def _dsn() -> str:
    return (
        f"host={os.getenv('PG_HOST', 'postgres')} "
        f"port={os.getenv('PG_PORT', '5432')} "
        f"dbname={os.getenv('PG_DATABASE', 'mplsdb')} "
        f"user={os.getenv('PG_USER', 'mpls')} "
        f"password={os.getenv('PG_PASSWORD', 'mpls_dev_password')}"
    )


def _pick_severity(mix: dict) -> str:
    return rng.choices(list(mix.keys()), weights=list(mix.values()), k=1)[0]


def seed(scenarios: list[dict], purge: bool = False) -> dict:
    """Insert customers, circuits, tickets and messages. Returns counts."""
    counts = {"customers": 0, "circuits": 0, "tickets": 0, "messages": 0, "embedded": 0}

    with psycopg.connect(_dsn(), autocommit=False) as conn:
        cur = conn.cursor()

        if purge:
            step("purging existing ticket / circuit / customer rows")
            cur.execute("TRUNCATE ticket_messages, tickets, circuits, customers CASCADE")

        # ---------- customers ----------
        for i, (name, segment) in enumerate(CUSTOMER_NAMES, start=1):
            cid = f"CUS-{i:04d}"
            cur.execute(
                """INSERT INTO customers (customer_id, name, segment, contact_email)
                   VALUES (%s, %s, %s, %s) ON CONFLICT (customer_id) DO NOTHING""",
                (cid, name, segment, f"contact{i:02d}@customer.example.th"),
            )
            counts["customers"] += 1

        # ---------- circuits ----------
        # Customers attach to access devices only (LPE / APE). More circuits
        # than devices, which is what makes "how many customers are affected"
        # a meaningful question at this scale.
        circuit_ids: list[str] = []
        for i in range(1, 36):
            circuit_id = f"CIR-25-{i:05d}"
            customer_id = f"CUS-{((i - 1) % len(CUSTOMER_NAMES)) + 1:04d}"
            device_id = ACCESS_DEVICES[(i - 1) % len(ACCESS_DEVICES)]
            if_name = rng.choice(
                [f for f in DEVICE_BY_ID[device_id]["ifaces"] if not f.startswith("Hu")]
            )
            cur.execute(
                """INSERT INTO circuits (circuit_id, customer_id, device_id, if_name,
                                         service_type, bandwidth_mbps, activated_on)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (circuit_id) DO NOTHING""",
                (
                    circuit_id, customer_id, device_id, if_name,
                    rng.choice(SERVICE_TYPES),
                    rng.choice([50, 100, 200, 300, 500, 1000]),
                    hours_ago(rng.uniform(4000, 30000)).date(),
                ),
            )
            circuit_ids.append(circuit_id)
            counts["circuits"] += 1

        circuits_by_device: dict[str, list[str]] = {}
        cur.execute("SELECT circuit_id, device_id FROM circuits")
        for circuit_id, device_id in cur.fetchall():
            circuits_by_device.setdefault(device_id, []).append(circuit_id)

        ticket_seq = 0

        def next_ticket_id() -> str:
            nonlocal ticket_seq
            ticket_seq += 1
            return f"TK-25-{ticket_seq:05d}"

        def insert_ticket(spec: dict, scenario_id: str | None) -> str:
            ticket_id = next_ticket_id()
            device_id = spec["device_id"]
            opened = hours_ago(spec["hours_ago"])
            closed = (
                hours_ago(spec["hours_ago"] - spec["closed_after_hours"])
                if spec.get("closed_after_hours")
                else None
            )
            circuit_id = None
            if device_id in circuits_by_device:
                circuit_id = rng.choice(circuits_by_device[device_id])
            cur.execute(
                """INSERT INTO tickets (ticket_id, category, severity, status, site_code,
                                        device_id, circuit_id, title, description,
                                        opened_at, closed_at, assignee, resolution)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    ticket_id, spec["category"], spec["severity"], spec["status"],
                    DEVICE_BY_ID[device_id]["site"], device_id, circuit_id,
                    spec["title"], spec["description"], opened, closed,
                    spec.get("assignee") or (
                        rng.choice(["somchai.p", "narumon.k", "witaya.s", "pornthip.r"])
                        if spec["status"] != "open" else None
                    ),
                    spec.get("resolution"),
                ),
            )
            for offset, (role, text) in enumerate(spec.get("messages", [])):
                cur.execute(
                    """INSERT INTO ticket_messages
                       (ticket_id, author, author_role, message, created_at)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (
                        ticket_id,
                        {"customer": "ลูกค้า", "engineer": "เจ้าหน้าที่ NOC",
                         "system": "system"}[role],
                        role, text,
                        hours_ago(spec["hours_ago"] - offset * 0.5),
                    ),
                )
                counts["messages"] += 1
            counts["tickets"] += 1
            return ticket_id

        # ---------- scenario tickets ----------
        for spec in scenarios:
            for ticket in spec.get("tickets", []) or []:
                insert_ticket(ticket, spec["id"])

        # ---------- filler tickets ----------
        filler = next((s for s in scenarios if s["id"] == "FILLER"), None)
        if filler:
            cfg = filler["filler_tickets"]
            excluded = set(cfg.get("exclude_devices", []))
            eligible = [d for d in ACCESS_DEVICES if d not in excluded]
            for _ in range(cfg["count"]):
                category = _pick_severity(cfg["category_mix"])
                status = _pick_severity(cfg["status_mix"])
                device_id = rng.choice(eligible)
                opened_h = rng.uniform(*sorted(cfg["window_hours_ago"], reverse=True))
                insert_ticket(
                    {
                        "device_id": device_id,
                        "category": category,
                        "severity": _pick_severity(cfg["severity_mix"]),
                        "status": status,
                        "hours_ago": opened_h,
                        "closed_after_hours": (
                            rng.uniform(2, 72) if status == "closed" else None
                        ),
                        "title": rng.choice(FILLER_TITLES[category]),
                        "description": (
                            "เคสทั่วไปที่บันทึกไว้ในระบบ ใช้เป็นข้อมูลพื้นหลัง "
                            "เพื่อให้การค้นหาและการจัดอันดับมีความหมาย"
                        ),
                        "resolution": (
                            "ดำเนินการแก้ไขเรียบร้อย" if status == "closed" else None
                        ),
                        "messages": [
                            ("customer", "แจ้งปัญหาตามหัวข้อครับ"),
                            ("engineer", "รับเรื่องแล้วครับ กำลังตรวจสอบ"),
                        ],
                    },
                    None,
                )

        conn.commit()

        # ---------- embeddings ----------
        # Ships populated so the demo works immediately. Lab 1 removes this
        # with `make lab1-reset` and asks participants to rebuild it.
        if embed.is_available():
            step("generating ticket embeddings")
            cur.execute("SELECT ticket_id, title, description FROM tickets ORDER BY ticket_id")
            rows = cur.fetchall()
            batch_size = 32
            for i in range(0, len(rows), batch_size):
                chunk = rows[i:i + batch_size]
                vectors = embed.embed_many([f"{t}\n\n{d}" for _, t, d in chunk])
                if not vectors:
                    break
                for (ticket_id, _, _), vec in zip(chunk, vectors):
                    cur.execute(
                        "UPDATE tickets SET embedding = %s WHERE ticket_id = %s",
                        (str(vec), ticket_id),
                    )
                    counts["embedded"] += 1
            conn.commit()

    return counts
