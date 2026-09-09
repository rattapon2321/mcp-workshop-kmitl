"""Shared fixtures.

Tests that need live services skip rather than fail when those services are
down. A participant should be able to run the unit tests on a laptop with
nothing started, and get the full suite once `make up` has run.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "agent-api"))
sys.path.insert(0, str(ROOT / "apps" / "mcp-server"))
sys.path.insert(0, str(ROOT / "docker" / "loader"))


def _service_up(url: str) -> bool:
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=1):
            return True
    except OSError:
        return False


needs_postgres = pytest.mark.skipif(
    not _service_up("http://localhost:5432"), reason="PostgreSQL not running (make up)"
)
needs_neo4j = pytest.mark.skipif(
    not _service_up("http://localhost:7687"), reason="Neo4j not running (make up)"
)
needs_opensearch = pytest.mark.skipif(
    not _service_up("http://localhost:9200"), reason="OpenSearch not running (make up)"
)
needs_llm = pytest.mark.skipif(
    not _service_up(os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")),
    reason="LLM endpoint not reachable",
)


@pytest.fixture(scope="session")
def questions() -> dict:
    """Every golden question, keyed by id."""
    import yaml

    result: dict = {}
    for path in sorted((ROOT / "data" / "questions").glob("L*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in data.get("questions", []) or []:
            result[item["id"]] = item
    return result


@pytest.fixture(scope="session")
def conversation() -> dict:
    return json.loads(
        (ROOT / "data" / "challenge_fixtures" / "conversation_10turns.json")
        .read_text(encoding="utf-8")
    )


@pytest.fixture(scope="session")
def tool_cases() -> dict:
    return json.loads(
        (ROOT / "data" / "challenge_fixtures" / "tool_selection_cases.json")
        .read_text(encoding="utf-8")
    )


@pytest.fixture(scope="session")
def noisy_tickets() -> list:
    return json.loads(
        (ROOT / "data" / "challenge_fixtures" / "noisy_tickets.json")
        .read_text(encoding="utf-8")
    )
