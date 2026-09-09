"""Convert agent output into files that can be attached and shared.

Covers the "convert a file" capability from Workshop 2. Three formats, each
for a different consumer:

    markdown  a person reading it
    csv       a spreadsheet
    pdf       something to attach to a formal report

PDF generation degrades to Markdown when reportlab is not installed, because
a missing optional dependency should not fail a user's request.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("data/reports")


def _timestamped(extension: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR / f"export-{datetime.now():%Y%m%d-%H%M%S}.{extension}"


def to_markdown(title: str, sections: list[dict]) -> str:
    """sections: [{"heading": str, "body": str} | {"heading": str, "table": [dict]}]"""
    lines = [f"# {title}", "", f"สร้างเมื่อ {datetime.now():%Y-%m-%d %H:%M}", ""]
    for section in sections:
        lines += [f"## {section['heading']}", ""]
        if "table" in section and section["table"]:
            headers = list(section["table"][0].keys())
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("|" + "---|" * len(headers))
            for row in section["table"]:
                lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
        else:
            lines.append(section.get("body", ""))
        lines.append("")

    path = _timestamped("md")
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def to_csv(rows: list[dict]) -> str:
    if not rows:
        raise ValueError("ไม่มีข้อมูลให้ export")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

    path = _timestamped("csv")
    # utf-8-sig so Excel on Windows opens Thai text correctly. Without the BOM
    # every Thai character renders as mojibake, which is the single most common
    # complaint about exported reports.
    path.write_text(buffer.getvalue(), encoding="utf-8-sig")
    return str(path)


def to_pdf(title: str, body: str) -> str:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        return to_markdown(title, [{"heading": "เนื้อหา", "body": body}])

    path = _timestamped("pdf")
    document = SimpleDocTemplate(str(path), pagesize=A4)
    styles = getSampleStyleSheet()
    flow = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    for paragraph in body.split("\n\n"):
        flow += [Paragraph(paragraph.replace("\n", "<br/>"), styles["BodyText"]),
                 Spacer(1, 8)]
    document.build(flow)
    return str(path)
