#!/usr/bin/env python3
"""Workshop 2 reference solution: an agent loop written from scratch.

    python solutions/day2/workshop2_agent.py
    python solutions/day2/workshop2_agent.py "หา ticket ที่ยังไม่ปิด แล้วส่งสรุปให้ NOC"

No agent framework, and deliberately no MCP either - tools are plain Python
functions called directly. Day 3 replaces that layer with MCP and nothing else
about the loop changes, which is the point: the loop is the part worth
understanding, and it is about 200 lines.

Capabilities required by the curriculum: search, convert a file, send email.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import smtplib
import sys
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from enum import Enum
from pathlib import Path

import httpx
import psycopg
from neo4j import GraphDatabase
from opensearchpy import OpenSearch
from pydantic import BaseModel, Field

BANGKOK = timezone(timedelta(hours=7))
PG_DSN = os.getenv("PG_DSN",
                   "postgresql://mcp_reader:mcp_reader_password@localhost:5432/mplsdb")
LLM_BASE_URL = "https://openrouter.ai/api/v1"
LLM_MODEL = "openai/gpt-4o-mini"
OUTPUT_DIR = Path("data/reports")

MAX_STEPS = 8
MAX_SAME_TOOL = 3


# ==========================================================================
# 1. Tools
# ==========================================================================

def search_tickets(status: str | None = None, days: int = 7,
                   limit: int = 20) -> dict:
    """ค้นหา ticket ที่ถูกแจ้งเข้ามา

    ใช้เมื่อต้องการรู้ว่ามีอะไรถูก "แจ้ง" เข้ามาบ้าง
    อย่าใช้เพื่อดูพฤติกรรมของอุปกรณ์ - ให้ใช้ count_log_events แทน
    """
    since = datetime.now(BANGKOK) - timedelta(days=days)
    where = ["opened_at >= %s"]
    params: list = [since]
    if status:
        where.append("status = %s")
        params.append(status)

    with psycopg.connect(PG_DSN) as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT ticket_id, severity, status, site_code, device_id,
                       title, opened_at
                FROM tickets WHERE {' AND '.join(where)}
                ORDER BY opened_at DESC LIMIT %s""",
            tuple(params + [limit]),
        )
        rows = [
            {"ticket_id": r[0], "severity": r[1], "status": r[2],
             "site_code": r[3], "device_id": r[4], "title": r[5],
             "opened_at": r[6].isoformat()}
            for r in cur.fetchall()
        ]
    return {"count": len(rows), "tickets": rows}


def get_upstream_devices(device_ids: list[str]) -> dict:
    """หาอุปกรณ์ upstream ที่อุปกรณ์หลายตัวใช้ร่วมกัน

    ใช้เมื่อลูกค้าหลายรายที่อยู่คนละอุปกรณ์แจ้งอาการเดียวกัน
    เพราะสาเหตุร่วมมักอยู่ที่อุปกรณ์ที่ทุกตัวพึ่งพา ซึ่ง ticket จะไม่เอ่ยถึง
    """
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"),
              os.getenv("NEO4J_PASSWORD", "neo4j_dev_password")),
    )
    with driver, driver.session() as session:
        records = session.run(
            """UNWIND $ids AS start
               MATCH (d:Device {device_id: start})-[:UPLINK_TO*1..4]->(up:Device)
               RETURN start, up.device_id AS upstream""",
            ids=device_ids,
        ).data()

    dependents: dict[str, set] = {}
    for record in records:
        dependents.setdefault(record["upstream"], set()).add(record["start"])

    shared = sorted(
        ({"device_id": k, "dependent_count": len(v), "depends_on_it": sorted(v)}
         for k, v in dependents.items()),
        key=lambda x: -x["dependent_count"],
    )
    common = [s for s in shared if s["dependent_count"] == len(set(device_ids))]
    return {"upstream_devices": shared, "shared_by_all": common}


def count_log_events(days: int = 7, group_by: str = "device_id") -> dict:
    """นับ log events แยกตามอุปกรณ์หรือประเภทเหตุการณ์

    ใช้เมื่อถามว่า "กี่ครั้ง" หรือ "ตัวไหนเยอะที่สุด"
    อย่าใช้เมื่อต้องการอ่านข้อความ log จริง
    """
    client = OpenSearch(hosts=[os.getenv("OPENSEARCH_URL", "http://localhost:9200")])
    response = client.search(
        index="network-logs-*",
        body={
            "size": 0,
            "query": {"bool": {"must": [
                {"range": {"@timestamp": {"gte": f"now-{days}d"}}},
                {"terms": {"severity": ["critical", "error", "warning"]}},
            ]}},
            "aggs": {"grouped": {"terms": {"field": group_by, "size": 15}}},
        },
    )
    return {
        "total": response["hits"]["total"]["value"],
        "results": [{"key": b["key"], "count": b["doc_count"]}
                    for b in response["aggregations"]["grouped"]["buckets"]],
    }


def export_report(title: str, rows: list[dict], format: str = "markdown") -> dict:
    """แปลงข้อมูลเป็นไฟล์รายงาน (markdown, csv)

    ใช้เมื่อต้องการไฟล์ที่ส่งต่อให้คนอื่นได้
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(BANGKOK).strftime("%Y%m%d-%H%M%S")

    if format == "csv":
        buffer = io.StringIO()
        if rows:
            writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        path = OUTPUT_DIR / f"report-{stamp}.csv"
        # utf-8-sig so Excel on Windows renders Thai correctly. Without the
        # BOM every Thai character becomes mojibake, which is the single most
        # common complaint about exported reports.
        path.write_text(buffer.getvalue(), encoding="utf-8-sig")
    else:
        lines = [f"# {title}", "", f"สร้างเมื่อ {datetime.now(BANGKOK):%Y-%m-%d %H:%M}", ""]
        if rows:
            headers = list(rows[0].keys())
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("|" + "---|" * len(headers))
            for row in rows:
                lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
        path = OUTPUT_DIR / f"report-{stamp}.md"
        path.write_text("\n".join(lines), encoding="utf-8")

    return {"ok": True, "path": str(path), "rows": len(rows), "format": format}


def send_notification(subject: str, body: str, to: str | None = None,
                      attachment: str | None = None) -> dict:
    """ส่งอีเมลแจ้งเตือน (ไปที่ MailHog ไม่ออกนอกเครื่อง)

    ใช้เป็นขั้นตอนสุดท้ายเมื่อผู้ใช้ขอให้ส่งผลให้ทีม
    """
    to = to or os.getenv("NOTIFY_TO", "noc@example.local")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "agent@nt.local"
    message["To"] = to
    message.set_content(body)

    if attachment and Path(attachment).exists():
        data = Path(attachment).read_bytes()
        message.add_attachment(data, maintype="text", subtype="plain",
                               filename=Path(attachment).name)

    with smtplib.SMTP(os.getenv("SMTP_HOST", "localhost"),
                      int(os.getenv("SMTP_PORT", "1025")), timeout=10) as smtp:
        smtp.send_message(message)
    return {"ok": True, "to": to, "inspect_at": "http://localhost:8025"}


TOOLS = {
    "search_tickets": search_tickets,
    "get_upstream_devices": get_upstream_devices,
    "count_log_events": count_log_events,
    "export_report": export_report,
    "send_notification": send_notification,
}


# ==========================================================================
# 2. Plan schema
# ==========================================================================

class PlanStep(BaseModel):
    step: int = Field(ge=1)
    tool: str
    arguments: dict = Field(default_factory=dict)
    purpose: str
    depends_on: list[int] = Field(default_factory=list)
    argument_from: dict[str, str] = Field(
        default_factory=dict,
        description="{argument: 'step.N.path'} สำหรับค่าที่ยังไม่รู้จนกว่าขั้นก่อนจะรัน",
    )


class Plan(BaseModel):
    goal: str
    reasoning: str
    steps: list[PlanStep]


# ==========================================================================
# 3. Planner
# ==========================================================================

async def call_llm(messages: list[dict], schema: type[BaseModel] | None = None,
                   temperature: float = 0.0) -> str:
    # 1. บังคับชื่อโมเดลตรงนี้เลย
    payload: dict = {"model": "openai/gpt-4o-mini", "messages": messages,
                     "temperature": temperature, "max_tokens": 1500}
    if schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            # 2. เอา "strict": True ออกเพื่อป้องกัน OpenRouter งอแง
            "json_schema": {"name": schema.__name__,
                            "schema": schema.model_json_schema()},
        }
    async with httpx.AsyncClient(timeout=180) as client:
        # 3. บังคับ URL และใส่ API Key ตรงนี้
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions", json=payload,
            headers={"Authorization": "Bearer "},
        )
        
        # 4. ถ้า Error ให้ปริ้นท์สาเหตุที่แท้จริงออกมาโชว์
        if response.status_code != 200:
            print(f"\n🚨 [API ERROR จาก OpenRouter]: {response.text}\n")
            
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"] or ""


PLANNER_PROMPT = """\
วางแผนว่าจะใช้เครื่องมือใดตามลำดับใด เพื่อบรรลุเป้าหมายของผู้ใช้
คุณไม่ต้องตอบคำถาม - หน้าที่คือสร้างแผน

กติกา:
1. ใช้ขั้นตอนน้อยที่สุดที่ทำงานสำเร็จ
2. ใส่ depends_on เฉพาะเมื่อขั้นนั้นต้องใช้ผลของขั้นก่อนจริงๆ
3. พารามิเตอร์ที่ต้องอ้างอิงข้อมูลจากขั้นก่อน (เช่น step.1...) **ห้ามใส่ใน arguments เด็ดขาด** ให้ใส่ใน argument_from เท่านั้น!
   ตัวอย่างการเขียน JSON ของแต่ละขั้นตอน (ต้องมีฟิลด์ purpose เสมอ):
   {{
       "step": 2,
       "tool": "export_report",
       "purpose": "สร้างรายงานสรุปจากข้อมูล Ticket",
       "arguments": {{"title": "รายงาน Ticket", "format": "markdown"}},
       "argument_from": {{"rows": "step.1.tickets"}},
       "depends_on": [1]
   }}
4. ถ้าผู้ใช้ขอให้ส่งผลให้ทีม ต้องมีขั้น export_report ก่อน send_notification
   (และอย่าลืมแนบไฟล์รายงานในขั้น send_notification ด้วย "argument_from": {{"attachment": "step.2.path"}})

ความรู้ที่ต้องใช้:
- ถ้าลูกค้าหลายรายที่อยู่คนละอุปกรณ์แจ้งอาการเดียวกัน
  ให้หา upstream ร่วมด้วย get_upstream_devices ก่อนสรุป

เครื่องมือที่มี:
{catalogue}
"""


async def create_plan(goal: str) -> Plan:
    import inspect  # เพิ่มบรรทัดนี้เข้ามา
    catalogue = "\n\n".join(
        f"{name}{inspect.signature(fn)}: {(fn.__doc__ or '').strip()}" for name, fn in TOOLS.items()
    )
    raw = await call_llm(
        [
            {"role": "system", "content": PLANNER_PROMPT.format(catalogue=catalogue)},
            {"role": "user", "content": goal},
        ],
        schema=Plan,
    )
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text[4:] if text.lstrip().startswith("json") else text
    plan = Plan.model_validate_json(text.strip())

    # Validate BEFORE executing. A hallucinated tool name caught here costs
    # nothing; caught at execution time it costs a round trip and produces a
    # confusing error for the user.
    known = set(TOOLS)
    plan.steps = [s for s in plan.steps if s.tool in known]
    for step in plan.steps:
        step.depends_on = [d for d in step.depends_on if d < step.step]
    return plan


# ==========================================================================
# 4. Loop guard
# ==========================================================================

class LoopGuard:
    """Three independent stop conditions.

    Any one alone is defeatable:
      - a step budget alone lets a tight retry loop burn all 8 steps
      - blocking identical calls alone lets the model fuzz arguments forever
      - a per-tool cap alone lets two tools ping-pong
    Together they bound every loop shape seen in practice.
    """

    def __init__(self) -> None:
        self.total = 0
        self.signatures: dict[str, int] = {}
        self.tool_counts: dict[str, int] = {}

    def check(self, tool: str, arguments: dict) -> str | None:
        self.total += 1
        if self.total > MAX_STEPS:
            return f"เกิน {MAX_STEPS} ขั้นตอน"

        signature = f"{tool}:{json.dumps(arguments, sort_keys=True, default=str)}"
        self.signatures[signature] = self.signatures.get(signature, 0) + 1
        if self.signatures[signature] > 1:
            return f"เรียก {tool} ด้วย argument เดิมซ้ำ"

        self.tool_counts[tool] = self.tool_counts.get(tool, 0) + 1
        if self.tool_counts[tool] > MAX_SAME_TOOL:
            return f"เรียก {tool} เกิน {MAX_SAME_TOOL} ครั้ง"
        return None


# ==========================================================================
# 5. Executor
# ==========================================================================

def resolve(path: str, results: dict) -> object:
    """Resolve 'step.1.tickets.*.device_id' against previous results.

    The '*' form is what turns "the tickets from step 1" into "the list of
    device ids to pass to step 2" - without it, every multi-step plan would
    need the model to copy values by hand, which it does unreliably.
    """
    parts = path.split(".")
    if len(parts) < 2 or parts[0] != "step":
        return None
    step_number = int(parts[1])
    if step_number not in results or not results[step_number]["ok"]:
        return None

    value = results[step_number]["result"]
    for i, part in enumerate(parts[2:], start=2):
        if value is None:
            return None
        if part == "*":
            remainder = parts[i + 1:]
            if not isinstance(value, list):
                return None
            collected = []
            for item in value:
                current = item
                for key in remainder:
                    current = current.get(key) if isinstance(current, dict) else None
                    if current is None:
                        break
                if current is not None:
                    collected.append(current)
            return collected
        if isinstance(value, list):
            try:
                value = value[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


async def execute(plan: Plan) -> dict:
    guard = LoopGuard()
    results: dict = {}
    pending = {s.step: s for s in plan.steps}

    while pending:
        runnable = [s for s in pending.values()
                    if all(d in results for d in s.depends_on)]
        if not runnable:
            for step in pending.values():
                results[step.step] = {"ok": False, "tool": step.tool,
                                      "error": "ขั้นที่ต้องพึ่งพาไม่สำเร็จ"}
            break

        async def run(step: PlanStep) -> tuple[int, dict]:
            arguments = dict(step.arguments)
            for name, reference in step.argument_from.items():
                resolved = resolve(reference, results)
                if resolved is not None:
                    arguments[name] = resolved

            blocked = guard.check(step.tool, arguments)
            if blocked:
                print(f"    [{step.step}] {step.tool} - หยุด: {blocked}")
                return step.step, {"ok": False, "tool": step.tool, "error": blocked}

            print(f"    [{step.step}] {step.tool}({json.dumps(arguments, ensure_ascii=False)[:70]})")
            started = time.time()
            try:
                # Tools are synchronous; run them off the event loop so
                # independent steps really do overlap.
                result = await asyncio.to_thread(TOOLS[step.tool], **arguments)
                elapsed = int((time.time() - started) * 1000)
                print(f"        -> สำเร็จ {elapsed} ms")
                return step.step, {"ok": True, "tool": step.tool, "result": result}
            except Exception as exc:  # noqa: BLE001
                print(f"        -> ล้มเหลว: {type(exc).__name__}: {exc}")
                return step.step, {"ok": False, "tool": step.tool,
                                   "error": f"{type(exc).__name__}: {exc}"}

        completed = await asyncio.gather(*(run(s) for s in runnable))
        for number, outcome in completed:
            results[number] = outcome
            pending.pop(number, None)

    return results


# ==========================================================================
# 6. Synthesizer
# ==========================================================================

SYNTH_PROMPT = """\
สรุปผลเป็นภาษาไทยสำหรับวิศวกรโครงข่าย

กติกา:
- ตอบคำถามที่ถูกถามก่อน ไม่ต้องเริ่มด้วยการเล่าว่าทำอะไรไปบ้าง
- อ้างอิงแหล่งที่มาของทุกข้อสรุป เช่น (PostgreSQL: ticket TK-25-00001)
- ถ้าขั้นตอนไหนล้มเหลว ให้บอกตรงๆ ไม่ใช่เงียบไป
- ใช้เฉพาะข้อมูลในหลักฐาน ห้ามเติมสิ่งที่ไม่มี
"""


async def synthesize(goal: str, plan: Plan, results: dict) -> str:
    evidence = json.dumps(
        [{"step": k, **v} for k, v in sorted(results.items())],
        ensure_ascii=False, default=str,
    )[:10000]
    return await call_llm(
        [
            {"role": "system", "content": SYNTH_PROMPT},
            {"role": "system", "content": f"แผนที่ใช้: {plan.goal}\n{plan.reasoning}"},
            {"role": "system", "content": f"หลักฐาน:\n{evidence}"},
            {"role": "user", "content": goal},
        ],
        temperature=0.3,
    )


# ==========================================================================
# 7. Loop
# ==========================================================================

async def run(goal: str) -> None:
    print(f"\n{'=' * 68}\n  เป้าหมาย: {goal}\n{'=' * 68}\n")

    print("  [วางแผน]")
    started = time.time()
    plan = await create_plan(goal)
    print(f"    {plan.reasoning}\n")
    for step in plan.steps:
        depends = f" (รอขั้น {step.depends_on})" if step.depends_on else " (รันได้ทันที)"
        print(f"    {step.step}. {step.tool}{depends}")
        print(f"       {step.purpose}")

    print("\n  [ลงมือทำ]")
    results = await execute(plan)

    print("\n  [สรุป]")
    answer = await synthesize(goal, plan, results)
    print(f"\n{answer}\n")

    ok = sum(1 for r in results.values() if r["ok"])
    print(f"  {'-' * 66}")
    print(f"  {ok}/{len(results)} ขั้นตอนสำเร็จ · "
          f"ใช้เวลารวม {time.time() - started:.1f} วินาที")
    if any(r["tool"] == "send_notification" and r["ok"] for r in results.values()):
        print("  ตรวจอีเมลที่ http://localhost:8025")
    print()


DEFAULT_GOAL = ("หา ticket ที่ยังไม่ปิดของสัปดาห์นี้ "
                "ทำรายงานสรุป แล้วส่งเมลให้ทีม NOC")


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOAL))
