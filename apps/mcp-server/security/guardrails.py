"""Enforced guardrails.

The central lesson of Module 8: a guardrail written in a prompt is a request.
A guardrail written in code is a rule. This module contains rules.

Layers, outermost first:

  1. Read-only database roles     - the database itself refuses writes
  2. Query shape validation       - reject dangerous statements before sending
  3. Result caps                  - bounded rows, bounded response size
  4. Secret redaction             - nothing that looks like a credential leaves
  5. Audit log                    - every refusal is recorded

Challenge 5 asks participants to break these. Removing any single layer
should still leave the system safe, which is the property being taught.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import settings

audit_log = logging.getLogger("mcp.audit")

# --------------------------------------------------------------------------
# Query shape validation
# --------------------------------------------------------------------------

# Statements that modify data or schema. Matched as whole words so a ticket
# titled "ลูกค้าขอ update ข้อมูล" does not trip the filter.
_WRITE_KEYWORDS = [
    "insert", "update", "delete", "drop", "create", "alter", "truncate",
    "grant", "revoke", "merge", "set", "remove", "detach", "load csv",
    "call db.", "call apoc", "copy", "vacuum",
]

_WRITE_RE = re.compile(
    r"\b(" + "|".join(k.replace(" ", r"\s+") for k in _WRITE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Multiple statements in one string is the classic injection shape.
_MULTI_STATEMENT_RE = re.compile(r";\s*\S")


class GuardrailViolation(Exception):
    """Raised when a request is refused. The message is safe to show a user."""


@dataclass
class AuditEvent:
    tool: str
    decision: str
    reason: str
    detail: str = ""
    at: datetime = field(default_factory=datetime.now)

    def emit(self) -> None:
        audit_log.warning(
            "%s tool=%s reason=%s detail=%s",
            self.decision.upper(), self.tool, self.reason, self.detail[:200],
        )


def refuse(tool: str, reason: str, detail: str = "") -> None:
    """Record a refusal and raise. Never include internals in the message."""
    AuditEvent(tool=tool, decision="blocked", reason=reason, detail=detail).emit()
    raise GuardrailViolation(
        f"คำขอนี้ถูกปฏิเสธโดยระบบความปลอดภัย: {reason}. "
        f"เครื่องมือชุดนี้อ่านข้อมูลได้อย่างเดียว"
    )


def assert_read_only(query: str, tool: str) -> None:
    """Reject anything that could modify data.

    This runs even though the database accounts are already read-only.
    Defence in depth: the account protects the data, this check protects
    against a future misconfiguration and produces a clear audit record.
    """
    if _WRITE_RE.search(query):
        match = _WRITE_RE.search(query)
        refuse(tool, "พบคำสั่งที่แก้ไขข้อมูล", f"keyword={match.group(1)}")
    if _MULTI_STATEMENT_RE.search(query.strip().rstrip(";")):
        refuse(tool, "ส่งคำสั่งหลายชุดในครั้งเดียว", query[:120])


def cap_rows(rows: list, tool: str) -> tuple[list, bool]:
    """Bound the number of rows returned. Returns (rows, was_truncated).

    Truncation is reported to the model, never hidden. A silently truncated
    result set makes an agent state a total confidently and wrongly.
    """
    limit = settings().max_rows
    if len(rows) > limit:
        AuditEvent(
            tool=tool, decision="truncated",
            reason="result exceeded max_rows", detail=f"{len(rows)} -> {limit}",
        ).emit()
        return rows[:limit], True
    return rows, False


def clamp_limit(requested: int | None, tool: str, ceiling: int | None = None) -> int:
    """Clamp a caller-supplied limit into an allowed range."""
    ceiling = ceiling or settings().max_rows
    if requested is None:
        return min(20, ceiling)
    if requested < 1:
        return 1
    return min(requested, ceiling)


# --------------------------------------------------------------------------
# Secret redaction
# --------------------------------------------------------------------------

# The leading [\w-]* matters: real config uses prefixed names such as
# PG_PASSWORD and NEO4J_PASSWORD, and \bpassword\b does not match inside
# those because an underscore is a word character.
_SECRET_NAME = r"[\w-]*(?:password|passwd|secret|api[_-]?key|token|credential)s?"

_SECRET_PATTERNS = [
    re.compile(rf"(?i)\b({_SECRET_NAME})\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(snmp-server\s+community)\s+\S+"),
    re.compile(r"(?i)\b(authentication\s+key)\s+\S+"),
    # Long base64-ish blobs are usually keys.
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
]

# Used when the SECRET IS THE VALUE and the name lives in a dict key, where no
# single string contains both halves for the patterns above to match.
_SECRET_KEY_RE = re.compile(rf"(?i)^{_SECRET_NAME}$")


def redact(text: str) -> str:
    """Strip anything that looks like a credential from outgoing text.

    Applied to every string a tool returns, including data read from the
    database, because a config snippet can contain a community string.
    """
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(
            lambda m: f"{m.group(1)}: [REDACTED]" if m.groups() else "[REDACTED]",
            result,
        )
    return result


def redact_deep(value):
    """Recursively redact strings inside dicts and lists.

    A dict needs its own rule: in {"password": "hunter2"} neither the key nor
    the value alone looks like a credential to the regexes above, so the value
    is redacted based on what the key is called.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if isinstance(k, str) and _SECRET_KEY_RE.match(k)
            else redact_deep(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_deep(v) for v in value]
    return value


# --------------------------------------------------------------------------
# Filesystem sandbox
# --------------------------------------------------------------------------

def safe_path(relative: str, root: str, tool: str) -> Path:
    """Resolve a path and refuse anything that escapes the sandbox root.

    Both `../../etc/passwd` and a symlink pointing outside are caught,
    because the comparison happens after resolve().
    """
    root_path = Path(root).resolve()
    candidate = (root_path / relative).resolve()
    if not candidate.is_relative_to(root_path):
        refuse(tool, "เส้นทางไฟล์อยู่นอกขอบเขตที่อนุญาต", relative)
    if not candidate.exists():
        raise GuardrailViolation(f"ไม่พบไฟล์: {relative}")
    return candidate


def assert_allowlisted_script(name: str, allowed: set[str], tool: str) -> None:
    """Only scripts on the allowlist may run. No arbitrary command execution."""
    if name not in allowed:
        refuse(
            tool, "สคริปต์นี้ไม่อยู่ในรายการที่อนุญาต",
            f"requested={name} allowed={sorted(allowed)}",
        )
