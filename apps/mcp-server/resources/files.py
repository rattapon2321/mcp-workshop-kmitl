"""Expose a sandboxed documentation folder as Resources.

Demonstrates the Resource half of Workshop 3: giving a model safe read access
to a filesystem. Three rules make it safe:

  1. One fixed root. Paths are resolved and rejected if they escape it,
     which catches both ../ traversal and symlinks pointing outside.
  2. An extension allowlist. Only text formats are served.
  3. A size cap. A large file is truncated with a clear marker rather than
     silently flooding the context window.
"""

from __future__ import annotations

import json
from pathlib import Path

from config import settings
from security import guardrails

ALLOWED_SUFFIXES = {".md", ".txt", ".cfg", ".conf", ".json", ".yaml", ".yml"}
MAX_FILE_CHARS = 40_000


def register(mcp) -> None:

    @mcp.resource("files://index")
    def index() -> str:
        """List every document available under the sandboxed root."""
        root = Path(settings().mock_fs_root)
        if not root.exists():
            return json.dumps({"error": f"ไม่พบโฟลเดอร์ {root}", "files": []})

        entries = []
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in ALLOWED_SUFFIXES:
                entries.append(
                    {
                        "path": str(path.relative_to(root)),
                        "size_bytes": path.stat().st_size,
                        "category": path.parent.name,
                    }
                )
        return json.dumps(
            {
                "root": str(root),
                "file_count": len(entries),
                "files": entries,
                "usage": "อ่านไฟล์ด้วย resource files://read/{path}",
            },
            ensure_ascii=False,
            indent=2,
        )

    @mcp.resource("files://read/{path}")
    def read_file(path: str) -> str:
        """Read one document from the sandboxed root.

        Args:
            path: path relative to the root, as listed by files://index
        """
        resolved = Path(settings().mock_fs_root)
        target = guardrails.safe_path(path, str(resolved), "files_read")

        if target.suffix not in ALLOWED_SUFFIXES:
            guardrails.refuse("files_read", "ชนิดไฟล์นี้ไม่อนุญาตให้อ่าน", target.suffix)

        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) > MAX_FILE_CHARS:
            content = (
                content[:MAX_FILE_CHARS]
                + f"\n\n[ตัดที่ {MAX_FILE_CHARS} ตัวอักษร - ไฟล์ยาวกว่านี้]"
            )
        return guardrails.redact(content)
