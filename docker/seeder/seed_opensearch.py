"""Seed OpenSearch: log documents and the embedded document index.

Two indices with very different characteristics:

  network-logs-*  high volume, append only, filtered by time and device.
                  No vectors: embedding every log line is expensive and
                  answers worse than a structured filter.

  network-docs    low volume, semantic search, knn_vector field.
                  Runbooks and device configs converted to Markdown, chunked
                  and embedded - the same pipeline production uses.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from common import anchor_now, banner, step
from opensearchpy import OpenSearch, helpers

import embed
import loggen

TEMPLATE_DIR = Path("/seed/opensearch")
LOG_INDEX = os.getenv("OPENSEARCH_LOG_INDEX", "network-logs")
DOC_INDEX = os.getenv("OPENSEARCH_DOC_INDEX", "network-docs")

# Runbooks shipped with the workshop. Deliberately written the way real
# operational documentation is written, so semantic search has to bridge
# vocabulary gaps between how customers describe problems and how engineers do.
RUNBOOKS = [
    {
        "doc_id": "RB-001",
        "title": "การตรวจสอบ ISIS adjacency ที่ไม่ขึ้น",
        "tags": ["isis", "adjacency", "troubleshooting"],
        "content": """# การตรวจสอบ ISIS adjacency ที่ไม่ขึ้น

## อาการ
adjacency ค้างอยู่ที่สถานะ Init หรือ Down ทั้งที่ interface อยู่ในสถานะ up ทั้งสองฝั่ง

## ลำดับการตรวจสอบ
1. ตรวจสอบ physical layer ก่อนเสมอ - optical power, error counter
2. ตรวจสอบว่า IS-type ตรงกันทั้งสองฝั่ง (level-1 กับ level-2 คุยกันไม่ได้)
3. **ตรวจสอบค่า MTU ทั้งสองฝั่ง** - ISIS ส่ง hello PDU แบบ padded เต็ม MTU
   ถ้าสองฝั่งตั้งไม่เท่ากัน hello จะถูก drop และ adjacency จะไม่มีทางขึ้น
   อาการนี้พบบ่อยมากหลังเปลี่ยนอุปกรณ์ เพราะอุปกรณ์ใหม่มักมาพร้อม MTU default 1500
4. ตรวจสอบ authentication key ถ้าเปิดใช้งาน
5. ตรวจสอบ area ID / NET address

## การแก้ไขกรณี MTU mismatch
ปรับ MTU ฝั่งที่ตั้งผิดให้ตรงกับอีกฝั่ง โดยทั่วไปโครงข่าย backbone ใช้ 9000
หลังปรับแล้ว adjacency มักขึ้นเองภายใน hello interval ถัดไป ไม่ต้อง reload
""",
    },
    {
        "doc_id": "RB-002",
        "title": "การวินิจฉัยปัญหาเน็ตหลุดเป็นช่วง (intermittent drop)",
        "tags": ["intermittent", "flapping", "troubleshooting"],
        "content": """# การวินิจฉัยปัญหาเน็ตหลุดเป็นช่วง

## ทำไมเคสประเภทนี้ถึงยาก
ตอนที่เจ้าหน้าที่เข้าไปทดสอบ ระบบมักกลับมาปกติแล้ว ทำให้เคสถูกปิดโดยไม่ได้แก้อะไร
และลูกค้าจะเปิดเคสใหม่ซ้ำอีกในไม่กี่วัน

## หลักการสำคัญ
อย่าดูเฉพาะอุปกรณ์ที่ลูกค้าต่ออยู่ ให้ไล่ขึ้นไปหา upstream ด้วยเสมอ
**ถ้ามีลูกค้าหลายรายที่อยู่คนละอุปกรณ์แจ้งอาการเดียวกันในช่วงเวลาใกล้เคียงกัน
ให้สงสัยอุปกรณ์ที่เป็นจุดร่วมของทุกรายก่อน**

## ลำดับการตรวจสอบ
1. รวบรวม ticket ที่มีอาการคล้ายกันในช่วง 2-4 สัปดาห์
2. หา upstream ของอุปกรณ์ที่ลูกค้าแต่ละรายเชื่อมต่ออยู่
3. ถ้าพบอุปกรณ์ที่เป็นจุดร่วม ให้ตรวจ log ของอุปกรณ์นั้นในช่วงเวลาที่ลูกค้าแจ้ง
4. มองหา pattern ของ link up/down ซ้ำๆ (flapping) โดยเฉพาะที่ interface uplink
5. ตรวจสอบ optical power, SFP, และสายไฟเบอร์ของ interface ที่ flap

## สัญญาณของ interface flapping
log ที่เห็นซ้ำเป็นชุด: LINK-UPDOWN down ตามด้วย LINEPROTO down,
ISIS adjacency down แล้วกลับขึ้นภายในไม่กี่สิบวินาที วนซ้ำหลายรอบต่อวัน
""",
    },
    {
        "doc_id": "RB-003",
        "title": "การประเมินสุขภาพอุปกรณ์ (Equipment Health Score)",
        "tags": ["health", "proactive", "monitoring"],
        "content": """# การประเมินสุขภาพอุปกรณ์

## แนวคิด
อุปกรณ์ที่กำลังจะเสียมักส่งสัญญาณล่วงหน้าเป็นสัปดาห์ ก่อนที่ลูกค้าจะรู้สึกได้
การรอให้มี ticket ก่อนจึงเข้าไปดู คือการรอให้สายเกินไป

## ตัวชี้วัดที่ใช้
- อัตราการเกิด CRC error และ **แนวโน้ม** ของอัตรานั้น
- CPU utilisation ที่สูงต่อเนื่อง
- อุณหภูมิและความเร็วพัดลม
- จำนวน packet drop
- ความถี่ของ interface flap

## จุดที่มักประเมินผิด
การนับจำนวน error สะสมทั้งหมดจะทำให้อุปกรณ์ที่เคยมีปัญหาหนักครั้งเดียวเมื่อนานมาแล้ว
ดูแย่กว่าอุปกรณ์ที่กำลังเสื่อมลงเรื่อยๆ ในตอนนี้
**ต้องให้น้ำหนักกับแนวโน้มที่เพิ่มขึ้น มากกว่าจำนวนสะสม**

## อุปกรณ์ที่ไม่มี ticket ไม่ได้แปลว่าสุขภาพดี
อุปกรณ์ที่เสื่อมเงียบมักไม่มี ticket เลย เพราะอาการยังไม่ถึงระดับที่ลูกค้าสังเกตเห็น
""",
    },
    {
        "doc_id": "RB-004",
        "title": "การแยกแยะเหตุเสียจริงกับงานบำรุงรักษาตามแผน",
        "tags": ["maintenance", "false-positive", "alerting"],
        "content": """# การแยกแยะเหตุเสียจริงกับงานบำรุงรักษาตามแผน

## ปัญหา
งาน maintenance ที่มีการ reload อุปกรณ์ จะสร้าง log ที่หน้าตาเหมือนเหตุเสียร้ายแรงทุกประการ
ทั้ง SYS-RELOAD, LINK-UPDOWN และ adjacency down หลายเส้นพร้อมกัน

## กติกาที่ต้องทำทุกครั้งก่อนประกาศว่าเป็นเหตุเสีย
**ตรวจสอบ ticket ประเภท maintenance ที่ครอบคลุมช่วงเวลานั้นก่อนเสมอ**
ถ้าพบ ticket ที่หน้าต่างเวลาตรงกัน ให้รายงานว่าเป็นงานตามแผน พร้อมอ้างอิงเลข ticket

## ทำไมถึงสำคัญ
การแจ้งเตือนผิดพลาดซ้ำๆ ทำให้ทีมงานเริ่มเพิกเฉยต่อการแจ้งเตือน
และเมื่อเกิดเหตุเสียจริงจะไม่มีใครสนใจ
""",
    },
    {
        "doc_id": "RB-005",
        "title": "ขั้นตอนการแจ้งผลกระทบต่อลูกค้าก่อนปิดอุปกรณ์ซ่อม",
        "tags": ["maintenance", "customer-impact", "procedure"],
        "content": """# ขั้นตอนการแจ้งผลกระทบก่อนปิดอุปกรณ์ซ่อม

## ก่อนกำหนดหน้าต่างงาน
1. ระบุอุปกรณ์ทั้งหมดที่อยู่ใต้อุปกรณ์ที่จะปิด
2. ระบุวงจรทั้งหมดที่วิ่งผ่านอุปกรณ์เหล่านั้น
3. แยกลูกค้าตามกลุ่ม Enterprise / SME / Government
   กลุ่ม Enterprise และ Government ต้องแจ้งล่วงหน้าอย่างน้อย 7 วัน
4. ตรวจสอบว่ามี ticket ที่ยังไม่ปิดของลูกค้ากลุ่มนี้อยู่หรือไม่
   ถ้ามี ควรพยายามแก้ไขไปพร้อมกันในหน้าต่างงานเดียว

## การเลือกหน้าต่างเวลา
ช่วง 22:00 - 02:00 เป็นช่วงที่กระทบน้อยที่สุดสำหรับลูกค้าองค์กร
แต่สำหรับลูกค้ากลุ่มค้าปลีกที่มีระบบ POS ควรหลีกเลี่ยงช่วงปิดร้าน
""",
    },
]


def _client() -> OpenSearch:
    return OpenSearch(
        hosts=[os.getenv("OPENSEARCH_URL", "http://opensearch:9200")],
        http_compress=True,
        timeout=60,
    )


def _chunk_markdown(text: str, max_chars: int = 900) -> list[str]:
    """Split Markdown on headings, then on length.

    Heading-aware chunking keeps a procedure and its steps together, which
    matters far more for retrieval quality than any clever overlap scheme.
    """
    sections, current = [], []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))

    chunks = []
    for section in sections:
        if len(section) <= max_chars:
            chunks.append(section.strip())
            continue
        buf = ""
        for para in section.split("\n\n"):
            if len(buf) + len(para) > max_chars and buf:
                chunks.append(buf.strip())
                buf = para
            else:
                buf = f"{buf}\n\n{para}" if buf else para
        if buf.strip():
            chunks.append(buf.strip())
    return [c for c in chunks if c]


def seed(scenarios: list[dict], purge: bool = False) -> dict:
    counts = {"log_docs": 0, "doc_chunks": 0, "embedded": 0}
    client = _client()
    log_index = f"{LOG_INDEX}-000001"

    # ---------- index templates ----------
    for template_file, name in (
        ("log_index_template.json", "network-logs"),
        ("doc_index_template.json", "network-docs"),
    ):
        body = json.loads((TEMPLATE_DIR / template_file).read_text(encoding="utf-8"))
        client.indices.put_index_template(name=name, body=body)
        step(f"index template applied: {name}")

    if purge:
        step("purging existing indices")
        client.indices.delete(index=f"{LOG_INDEX}-*", ignore=[404])
        client.indices.delete(index=DOC_INDEX, ignore=[404])

    for index in (log_index, DOC_INDEX):
        if not client.indices.exists(index=index):
            client.indices.create(index=index)

    # ---------- logs ----------
    all_docs: list[dict] = []
    for spec in scenarios:
        if not spec.get("total_lines"):
            continue
        docs = loggen.generate(spec)
        step(f"{spec['id']:<8} {len(docs):>5} log lines")
        all_docs.extend(docs)

    actions = [{"_index": log_index, "_source": doc} for doc in all_docs]
    helpers.bulk(client, actions, chunk_size=500, request_timeout=120)
    counts["log_docs"] = len(actions)

    # ---------- documents ----------
    doc_actions = []
    embeddable_texts = []
    for runbook in RUNBOOKS:
        for i, chunk in enumerate(_chunk_markdown(runbook["content"])):
            doc_actions.append(
                {
                    "_index": DOC_INDEX,
                    "_id": f"{runbook['doc_id']}#{i}",
                    "_source": {
                        "doc_id": runbook["doc_id"],
                        "chunk_id": f"{runbook['doc_id']}#{i}",
                        "chunk_index": i,
                        "title": runbook["title"],
                        "source_type": "runbook",
                        "tags": runbook["tags"],
                        "content": chunk,
                        "token_count": len(chunk) // 3,
                        "updated_at": anchor_now().isoformat(),
                    },
                }
            )
            embeddable_texts.append(f"{runbook['title']}\n\n{chunk}")

    # Device configs from PostgreSQL are documents too - the ingestion lab
    # extends this exact path with the customer's own network documentation.
    import psycopg

    dsn = (
        f"host={os.getenv('PG_HOST', 'postgres')} "
        f"dbname={os.getenv('PG_DATABASE', 'mplsdb')} "
        f"user={os.getenv('PG_USER', 'mpls')} "
        f"password={os.getenv('PG_PASSWORD', 'mpls_dev_password')}"
    )
    with psycopg.connect(dsn) as conn:
        cur = conn.cursor()
        cur.execute("SELECT device_id, config_markdown FROM device_configs")
        for device_id, markdown in cur.fetchall():
            for i, chunk in enumerate(_chunk_markdown(markdown)):
                doc_actions.append(
                    {
                        "_index": DOC_INDEX,
                        "_id": f"CFG-{device_id}#{i}",
                        "_source": {
                            "doc_id": f"CFG-{device_id}",
                            "chunk_id": f"CFG-{device_id}#{i}",
                            "chunk_index": i,
                            "title": f"Running configuration: {device_id}",
                            "source_type": "config",
                            "device_id": device_id,
                            "tags": ["config"],
                            "content": chunk,
                            "token_count": len(chunk) // 3,
                            "updated_at": anchor_now().isoformat(),
                        },
                    }
                )
                embeddable_texts.append(chunk)

    if embed.is_available():
        step(f"embedding {len(embeddable_texts)} document chunks")
        batch = 32
        vectors: list[list[float]] = []
        for i in range(0, len(embeddable_texts), batch):
            part = embed.embed_many(embeddable_texts[i:i + batch])
            if not part:
                vectors = []
                break
            vectors.extend(part)
        if vectors:
            for action, vec in zip(doc_actions, vectors):
                action["_source"]["embedding"] = vec
            counts["embedded"] = len(vectors)

    helpers.bulk(client, doc_actions, chunk_size=100, request_timeout=120)
    counts["doc_chunks"] = len(doc_actions)

    client.indices.refresh(index=f"{LOG_INDEX}-*")
    client.indices.refresh(index=DOC_INDEX)
    return counts
