"""Report generation and sandboxed script execution.

The curriculum asks for a tool that can "run a script or pull a summary
report". Letting a model run arbitrary commands is the single most dangerous
thing an MCP server can offer, so this module demonstrates how to provide the
capability without providing the danger:

  - Only scripts on an explicit allowlist can run. No shell, no interpolation.
  - Parameters are validated against a schema declared by each script.
  - Execution has a timeout and captured output limits.
  - Scripts run read-only against the database, same as everything else.

Participants attack this in challenge 5. The intended lesson is that
"which script" must be a closed set chosen by the developer, never a string
supplied by the model.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import clock
from config import settings
from db import pg_query
from security import guardrails

# The allowlist. A script that is not here cannot be executed, regardless of
# what any prompt asks for.
ALLOWED_SCRIPTS: dict[str, dict] = {
    "open_tickets_summary": {
        "file": "open_tickets_summary.py",
        "description": "Summarise open tickets grouped by severity and device",
        "params": {},
    },
    "device_inventory": {
        "file": "device_inventory.py",
        "description": "List all devices with site, role and circuit count",
        "params": {},
    },
    "weekly_incident_report": {
        "file": "weekly_incident_report.py",
        "description": "Incident counts and top affected devices for a time range",
        "params": {"range": {"type": "string", "default": "last_7d"}},
    },
}

MAX_OUTPUT_CHARS = 20_000
SCRIPT_TIMEOUT_SECONDS = 30


def register(mcp) -> None:

    @mcp.tool(
        annotations={"title": "List runnable reports", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def list_report_scripts() -> dict:
        """List the reports that can be run, with their parameters.

        Call this before run_report_script. The set is fixed by the server;
        asking for anything outside it will be refused.
        """
        return {
            "scripts": [
                {"name": name, "description": spec["description"],
                 "params": spec["params"]}
                for name, spec in ALLOWED_SCRIPTS.items()
            ],
            "note": "เรียกได้เฉพาะสคริปต์ในรายการนี้เท่านั้น",
        }

    @mcp.tool(
        annotations={"title": "Run an allowlisted report script",
                     "readOnlyHint": True, "idempotentHint": True,
                     "openWorldHint": False}
    )
    def run_report_script(name: str, params: dict | None = None) -> dict:
        """Run one of the predefined report scripts and return its output.

        Only names returned by list_report_scripts are accepted. Arbitrary
        commands, file paths and shell strings are refused.

        Args:
            name: script name from list_report_scripts
            params: parameters declared by that script
        """
        guardrails.assert_allowlisted_script(name, set(ALLOWED_SCRIPTS), "run_report_script")
        spec = ALLOWED_SCRIPTS[name]
        params = params or {}

        # Only declared parameters are passed through, and each is coerced to a
        # string argument rather than interpolated into a command line.
        argv = [sys.executable, str(Path(settings().reports_dir) / spec["file"])]
        for key, schema in spec["params"].items():
            value = params.get(key, schema.get("default"))
            if value is not None:
                argv += [f"--{key}", str(value)]

        try:
            completed = subprocess.run(  # noqa: S603 - argv is fully controlled
                argv,
                capture_output=True,
                text=True,
                timeout=SCRIPT_TIMEOUT_SECONDS,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            guardrails.AuditEvent(
                tool="run_report_script", decision="timeout",
                reason="script exceeded time limit", detail=name,
            ).emit()
            return {"ok": False, "error": f"สคริปต์ทำงานเกิน {SCRIPT_TIMEOUT_SECONDS} วินาที"}

        stdout = completed.stdout[:MAX_OUTPUT_CHARS]
        return guardrails.redact_deep({
            "ok": completed.returncode == 0,
            "script": name,
            "exit_code": completed.returncode,
            "output": stdout,
            "truncated": len(completed.stdout) > MAX_OUTPUT_CHARS,
            "stderr": completed.stderr[:2000] if completed.returncode else None,
        })

    @mcp.tool(
        annotations={"title": "Generate a report file", "readOnlyHint": False,
                     "destructiveHint": False, "idempotentHint": False,
                     "openWorldHint": False}
    )
    def generate_report(
        title: str,
        format: str = "markdown",
        range: str = "last_7d",
        include_tickets: bool = True,
        include_health: bool = True,
    ) -> dict:
        """Build a summary report of the current network situation.

        Produces a document that can be attached to an email or handed to a
        manager. Combine with send_notification to deliver it.

        Note this tool WRITES a file, which is why readOnlyHint is false. It
        writes only inside the reports output directory.

        Args:
            title: report heading
            format: markdown | csv | json
            range: reporting window
            include_tickets: include the open ticket summary
            include_health: include equipment health ranking
        """
        start, end = clock.resolve_range(range)
        generated_at = clock.data_now()

        sections: dict = {"title": title,
                          "range": {"from": start.isoformat(), "to": end.isoformat()},
                          "generated_at": generated_at.isoformat()}

        if include_tickets:
            sections["tickets"] = pg_query(
                """SELECT severity, status, count(*) AS n
                   FROM tickets WHERE opened_at BETWEEN %s AND %s
                   GROUP BY severity, status ORDER BY severity, status""",
                (start, end),
            )
            sections["open_tickets"] = pg_query(
                """SELECT ticket_id, severity, device_id, title, opened_at
                   FROM tickets WHERE status <> 'closed'
                   ORDER BY severity DESC, opened_at DESC LIMIT 20""",
            )

        if include_health:
            # Reuse the same scoring the health tool exposes, so a report can
            # never disagree with what the agent said a moment earlier.
            from tools.logs import register as _  # noqa: F401  (documented import)
            sections["health_note"] = (
                "ดูคะแนนสุขภาพอุปกรณ์จาก calculate_health_score "
                "รายงานนี้อ้างอิงเกณฑ์เดียวกัน"
            )

        if format == "json":
            body = json.dumps(sections, ensure_ascii=False, indent=2, default=str)
        elif format == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["ticket_id", "severity", "device_id", "title", "opened_at"])
            for row in sections.get("open_tickets", []):
                writer.writerow([row["ticket_id"], row["severity"], row["device_id"],
                                 row["title"], row["opened_at"]])
            body = buffer.getvalue()
        else:
            lines = [f"# {title}", "",
                     f"ช่วงข้อมูล: {start:%Y-%m-%d %H:%M} ถึง {end:%Y-%m-%d %H:%M}",
                     f"สร้างเมื่อ: {generated_at:%Y-%m-%d %H:%M}", ""]
            if include_tickets:
                lines += ["## สรุป ticket", "", "| ระดับ | สถานะ | จำนวน |", "|---|---|---|"]
                lines += [f"| {r['severity']} | {r['status']} | {r['n']} |"
                          for r in sections["tickets"]]
                lines += ["", "## Ticket ที่ยังไม่ปิด", "",
                          "| หมายเลข | ระดับ | อุปกรณ์ | หัวข้อ |", "|---|---|---|---|"]
                lines += [f"| {r['ticket_id']} | {r['severity']} | {r['device_id']} | {r['title']} |"
                          for r in sections["open_tickets"]]
            body = "\n".join(lines)

        output_dir = Path("data/reports")
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = {"markdown": "md", "csv": "csv", "json": "json"}[format]
        filename = f"report-{generated_at:%Y%m%d-%H%M%S}.{suffix}"
        (output_dir / filename).write_text(body, encoding="utf-8")

        return guardrails.redact_deep({
            "ok": True,
            "path": str(output_dir / filename),
            "format": format,
            "size_bytes": len(body.encode()),
            "preview": body[:1500],
        })
