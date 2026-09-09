"""Guardrails must hold as pure code, before any database is involved.

Challenge 5 asks participants to defeat these. Every case here is an attack
that must fail regardless of what a prompt says.
"""

from __future__ import annotations

import pytest
from security import guardrails


class TestReadOnlyEnforcement:
    @pytest.mark.parametrize("query", [
        "MATCH (n) DETACH DELETE n",
        "DROP TABLE tickets",
        "UPDATE tickets SET severity='low'",
        "delete from tickets",
        "TRUNCATE tickets CASCADE",
        "MATCH (n:Device) SET n.status='down'",
        "GRANT ALL ON tickets TO public",
    ])
    def test_write_statements_refused(self, query):
        with pytest.raises(guardrails.GuardrailViolation):
            guardrails.assert_read_only(query, "test")

    @pytest.mark.parametrize("query", [
        "SELECT * FROM tickets WHERE status='open'",
        "MATCH (d:Device) RETURN d LIMIT 10",
    ])
    def test_read_statements_allowed(self, query):
        guardrails.assert_read_only(query, "test")

    def test_multiple_statements_refused(self):
        with pytest.raises(guardrails.GuardrailViolation):
            guardrails.assert_read_only(
                "SELECT 1; SELECT * FROM tickets", "test"
            )


class TestSecretRedaction:
    @pytest.mark.parametrize("text,leaked", [
        ("password: hunter2", "hunter2"),
        ("PG_PASSWORD=mpls_dev_password", "mpls_dev_password"),
        ("snmp-server community s3cr3tstring RO", "s3cr3tstring"),
        ("api_key: sk-abcdef123456", "sk-abcdef123456"),
    ])
    def test_secrets_are_removed(self, text, leaked):
        assert leaked not in guardrails.redact(text)

    def test_redaction_is_recursive(self):
        payload = {"config": ["snmp-server community topsecret RO"],
                   "nested": {"password": "abc123"}}
        result = str(guardrails.redact_deep(payload))
        assert "topsecret" not in result and "abc123" not in result


class TestPathSandbox:
    @pytest.mark.parametrize("path", [
        "../../.env",
        "../../../etc/passwd",
        "runbooks/../../../../etc/hosts",
    ])
    def test_traversal_refused(self, tmp_path, path):
        (tmp_path / "runbooks").mkdir()
        with pytest.raises(guardrails.GuardrailViolation):
            guardrails.safe_path(path, str(tmp_path), "test")

    def test_legitimate_path_allowed(self, tmp_path):
        (tmp_path / "runbooks").mkdir()
        (tmp_path / "runbooks" / "a.md").write_text("hello")
        resolved = guardrails.safe_path("runbooks/a.md", str(tmp_path), "test")
        assert resolved.read_text() == "hello"


class TestScriptAllowlist:
    def test_unknown_script_refused(self):
        with pytest.raises(guardrails.GuardrailViolation):
            guardrails.assert_allowlisted_script(
                "../../etc/passwd", {"open_tickets_summary"}, "test"
            )

    def test_allowlisted_script_permitted(self):
        guardrails.assert_allowlisted_script(
            "open_tickets_summary", {"open_tickets_summary"}, "test"
        )


class TestResultCaps:
    def test_rows_are_capped_and_flagged(self, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings(), "max_rows", 5)
        rows, truncated = guardrails.cap_rows(list(range(100)), "test")
        assert len(rows) == 5 and truncated is True

    def test_limit_is_clamped(self):
        assert guardrails.clamp_limit(99999, "test", ceiling=50) == 50
        assert guardrails.clamp_limit(-3, "test") == 1
