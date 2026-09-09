#!/usr/bin/env python3
"""Health check for the whole workshop stack.

Run with `make verify`. Exits non-zero if anything is missing, so it can be
used as an acceptance test - including at the 30-day follow-up review, where
the objective is exactly this: confirm all three databases are connected,
populated and reachable through MCP.

Every check prints what it expected and what it found, because "verification
failed" without a number is not verification.
"""

from __future__ import annotations

import os
import sys

FAILURES: list[str] = []
WARNINGS: list[str] = []


def check(name: str, actual, expected, comparison: str = "eq") -> None:
    ok = {
        "eq": lambda a, e: a == e,
        "gte": lambda a, e: a >= e,
        "zero": lambda a, e: a == 0,
    }[comparison](actual, expected)
    mark = "PASS" if ok else "FAIL"
    detail = f"expected {'>= ' if comparison == 'gte' else ''}{expected}, found {actual}"
    print(f"  [{mark}] {name:<46} {detail}")
    if not ok:
        FAILURES.append(f"{name}: {detail}")


def warn(name: str, message: str) -> None:
    print(f"  [WARN] {name:<46} {message}")
    WARNINGS.append(f"{name}: {message}")


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * 62}")


def verify_postgres() -> None:
    import psycopg

    section("PostgreSQL - tickets, configs, circuits")
    dsn = (
        f"host={os.getenv('PG_HOST', 'postgres')} "
        f"dbname={os.getenv('PG_DATABASE', 'mplsdb')} "
        f"user={os.getenv('PG_USER', 'mpls')} "
        f"password={os.getenv('PG_PASSWORD', 'mpls_dev_password')}"
    )
    with psycopg.connect(dsn) as conn:
        cur = conn.cursor()

        cur.execute("SELECT count(*) FROM sites")
        check("sites", cur.fetchone()[0], 2)

        cur.execute("SELECT count(*) FROM devices")
        check("devices", cur.fetchone()[0], 10)

        cur.execute("SELECT count(*) FROM interfaces")
        check("interfaces", cur.fetchone()[0], 20, "gte")

        cur.execute("SELECT count(*) FROM circuits")
        check("circuits", cur.fetchone()[0], 35)

        cur.execute("SELECT count(*) FROM tickets")
        check("tickets", cur.fetchone()[0], 110, "gte")

        cur.execute("SELECT count(*) FROM ticket_messages")
        check("ticket messages", cur.fetchone()[0], 200, "gte")

        # Scenario S3: the MTU mismatch must exist or the scenario is broken.
        cur.execute("SELECT default_mtu FROM device_configs WHERE device_id = 'PE-NBI-04'")
        check("S3 PE-NBI-04 default MTU is wrong on purpose", cur.fetchone()[0], 1500)
        cur.execute("SELECT mtu FROM interfaces WHERE device_id='CR-BKK-02' AND if_name='Te0/0/3'")
        check("S3 CR-BKK-02 peer MTU", cur.fetchone()[0], 9000)

        # Scenario S2 depends on PE-BKK-02 having no tickets at all.
        cur.execute("SELECT count(*) FROM tickets WHERE device_id = 'PE-BKK-02'")
        check("S2 PE-BKK-02 has zero tickets", cur.fetchone()[0], 0, "zero")

        # Scenario S1: at least three tickets across the three LPEs.
        cur.execute(
            """SELECT count(DISTINCT device_id) FROM tickets
               WHERE device_id LIKE 'LPE-NBI-1%' AND category = 'intermittent'"""
        )
        check("S1 intermittent tickets span 3 LPEs", cur.fetchone()[0], 3)

        # Scenario S4: a maintenance ticket must exist for APE-BKK-05.
        cur.execute(
            """SELECT count(*) FROM tickets
               WHERE device_id = 'APE-BKK-05' AND category = 'maintenance'"""
        )
        check("S4 maintenance ticket exists", cur.fetchone()[0], 1, "gte")

        # Vectors: a warning rather than a failure, since the stack is usable
        # without them and the endpoint may legitimately be offline.
        cur.execute(
            """SELECT count(*) FROM information_schema.columns
               WHERE table_name = 'tickets' AND column_name = 'embedding'"""
        )
        has_column = cur.fetchone()[0] == 1
        if has_column:
            cur.execute("SELECT count(embedding) FROM tickets")
            embedded = cur.fetchone()[0]
            if embedded == 0:
                warn("ticket embeddings", "column exists but empty - run: make embed-tickets")
            else:
                check("ticket embeddings", embedded, 100, "gte")
        else:
            warn("ticket embeddings", "column absent - expected after `make lab1-reset`")

        # The read-only role must exist and must not be able to write.
        cur.execute("SELECT count(*) FROM pg_roles WHERE rolname = 'mcp_reader'")
        check("read-only role mcp_reader exists", cur.fetchone()[0], 1)

    ro_dsn = (
        f"host={os.getenv('PG_HOST', 'postgres')} "
        f"dbname={os.getenv('PG_DATABASE', 'mplsdb')} "
        f"user=mcp_reader password={os.getenv('PG_READONLY_PASSWORD', 'mcp_reader_password')}"
    )
    try:
        with psycopg.connect(ro_dsn) as conn:
            cur = conn.cursor()
            try:
                cur.execute("UPDATE tickets SET severity = 'low' WHERE false")
                conn.rollback()
                check("read-only role refuses writes", "allowed", "refused")
            except psycopg.errors.InsufficientPrivilege:
                check("read-only role refuses writes", "refused", "refused")
    except Exception as exc:  # noqa: BLE001
        warn("read-only role connection", f"{type(exc).__name__}: {exc}")


def verify_neo4j() -> None:
    from neo4j import GraphDatabase

    section("Neo4j - topology")
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"),
              os.getenv("NEO4J_PASSWORD", "neo4j_dev_password")),
    )
    with driver, driver.session() as session:
        def scalar(query: str):
            return session.run(query).single()[0]

        check("devices", scalar("MATCH (d:Device) RETURN count(d)"), 10)
        check("sites", scalar("MATCH (s:Site) RETURN count(s)"), 2)
        check("interfaces", scalar("MATCH (i:Interface) RETURN count(i)"), 20, "gte")
        check("circuits", scalar("MATCH (c:Circuit) RETURN count(c)"), 35)
        check("customers", scalar("MATCH (c:Customer) RETURN count(c)"), 30)

        # The structure scenario S1 depends on.
        check(
            "S1 three LPEs uplink to APE-NBI-03",
            scalar(
                """MATCH (l:Device)-[:UPLINK_TO]->(a:Device {device_id:'APE-NBI-03'})
                   RETURN count(l)"""
            ),
            3,
        )
        # The failed adjacency scenario S3 depends on.
        check(
            "S3 ISIS adjacency PE-NBI-04 is Down",
            scalar(
                """MATCH (:Device {device_id:'PE-NBI-04'})
                         -[r:ISIS_NEIGHBOR {state:'Down'}]->
                         (:Device {device_id:'CR-BKK-02'})
                   RETURN count(r)"""
            ),
            1,
        )
        # Cross-site path must be traversable end to end.
        check(
            "path LPE-NBI-11 -> CR-BKK-01 exists",
            scalar(
                """MATCH p = (:Device {device_id:'LPE-NBI-11'})
                            -[:UPLINK_TO*1..4]->
                            (:Device {device_id:'CR-BKK-01'})
                   RETURN count(p)"""
            ),
            1,
            "gte",
        )

        embedded = scalar("MATCH (d:Device) WHERE d.embedding IS NOT NULL RETURN count(d)")
        if embedded == 0:
            warn("device embeddings", "empty - run: make embed-devices")
        else:
            check("device embeddings", embedded, 10)


def verify_opensearch() -> None:
    from opensearchpy import OpenSearch

    section("OpenSearch - logs and documents")
    client = OpenSearch(hosts=[os.getenv("OPENSEARCH_URL", "http://opensearch:9200")], timeout=30)
    log_index = f"{os.getenv('OPENSEARCH_LOG_INDEX', 'network-logs')}-*"
    doc_index = os.getenv("OPENSEARCH_DOC_INDEX", "network-docs")

    total = client.count(index=log_index)["count"]
    check("log documents", total, 1800, "gte")

    def scenario_count(scenario: str) -> int:
        return client.count(
            index=log_index, body={"query": {"term": {"scenario": scenario}}}
        )["count"]

    check("S1 flapping log lines", scenario_count("S1"), 300, "gte")
    check("S2 degradation log lines", scenario_count("S2"), 250, "gte")
    check("S3 MTU mismatch log lines", scenario_count("S3"), 150, "gte")
    check("S4 maintenance log lines", scenario_count("S4"), 140, "gte")

    # The flap must actually be on APE-NBI-03, not scattered.
    flap = client.count(
        index=log_index,
        body={
            "query": {
                "bool": {
                    "must": [
                        {"term": {"device_id": "APE-NBI-03"}},
                        {"term": {"event_type": "LINK-UPDOWN"}},
                    ]
                }
            }
        },
    )["count"]
    check("S1 LINK-UPDOWN events on APE-NBI-03", flap, 60, "gte")

    docs = client.count(index=doc_index)["count"]
    check("document chunks", docs, 30, "gte")

    # data_now: the newest log timestamp is what the whole system treats as
    # "now". If this is far in the past, the demo will look empty.
    newest = client.search(
        index=log_index,
        body={"size": 1, "sort": [{"@timestamp": "desc"}], "_source": ["@timestamp"]},
    )["hits"]["hits"]
    if newest:
        print(f"  [INFO] data_now (newest log timestamp)       {newest[0]['_source']['@timestamp']}")

    mapping = client.indices.get_mapping(index=doc_index)
    has_vector = any(
        "embedding" in m["mappings"].get("properties", {}) for m in mapping.values()
    )
    check("knn_vector field present on network-docs", has_vector, True)


def main() -> int:
    print("\n" + "=" * 62)
    print("  Workshop stack verification")
    print("=" * 62)

    for fn in (verify_postgres, verify_neo4j, verify_opensearch):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] {fn.__name__}: {type(exc).__name__}: {exc}")
            FAILURES.append(f"{fn.__name__}: {exc}")

    print("\n" + "=" * 62)
    if FAILURES:
        print(f"  {len(FAILURES)} CHECK(S) FAILED")
        for failure in FAILURES:
            print(f"    - {failure}")
        print("\n  Try:  make reset && make up")
        print("=" * 62)
        return 1

    print("  ALL CHECKS PASSED")
    if WARNINGS:
        print(f"  {len(WARNINGS)} warning(s):")
        for warning in WARNINGS:
            print(f"    - {warning}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
