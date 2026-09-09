"""Status of every dependency, rendered for an audience.

Doubles as the acceptance check for the 30-day follow-up review, whose stated
objective is exactly this: confirm all three databases are connected and
reachable through MCP.
"""

from __future__ import annotations

import os

import httpx


def _check(name: str, fn) -> dict:
    try:
        detail = fn()
        return {"name": name, "ok": True, "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def collect() -> list[dict]:
    checks = []

    def postgres() -> str:
        import psycopg

        dsn = os.getenv("PG_DSN",
                        "postgresql://mcp_reader:mcp_reader_password@postgres:5432/mplsdb")
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            devices = conn.execute("SELECT count(*) FROM devices").fetchone()[0]
            tickets = conn.execute("SELECT count(*) FROM tickets").fetchone()[0]
        return f"{devices} อุปกรณ์ · {tickets} ticket"

    def neo4j() -> str:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"),
                  os.getenv("NEO4J_PASSWORD", "neo4j_dev_password")),
        )
        with driver, driver.session() as session:
            nodes = session.run("MATCH (n) RETURN count(n) AS n").single()["n"]
            rels = session.run("MATCH ()-[r]->() RETURN count(r) AS n").single()["n"]
        return f"{nodes} node · {rels} relationship"

    def opensearch() -> str:
        from opensearchpy import OpenSearch

        client = OpenSearch(hosts=[os.getenv("OPENSEARCH_URL", "http://opensearch:9200")],
                            timeout=5)
        logs = client.count(index="network-logs-*")["count"]
        docs = client.count(index="network-docs")["count"]
        return f"{logs:,} log · {docs} document chunk"

    def llm() -> str:
        base = os.getenv("LLM_BASE_URL", "http://host.docker.internal:11434/v1")
        response = httpx.get(f"{base.rstrip('/')}/models", timeout=5)
        response.raise_for_status()
        return os.getenv("LLM_MODEL", "gemma3:27b")

    for name, fn in (("PostgreSQL", postgres), ("Neo4j", neo4j),
                     ("OpenSearch", opensearch), ("LLM", llm)):
        checks.append(_check(name, fn))
    return checks


def render() -> str:
    """Markdown suitable for the top of the chat window."""
    checks = collect()
    rows = "\n".join(
        f"| {'🟢' if c['ok'] else '🔴'} | **{c['name']}** | {c['detail']} |"
        for c in checks
    )
    all_ok = all(c["ok"] for c in checks)
    header = "ระบบพร้อมใช้งาน" if all_ok else "มีบริการที่ยังไม่พร้อม"
    return f"### {header}\n\n| | ระบบ | สถานะ |\n|---|---|---|\n{rows}"
