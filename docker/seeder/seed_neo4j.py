"""Seed Neo4j: topology from Cypher files, then customers, circuits and vectors.

Topology lives in docker/neo4j/seed/*.cypher because it is easier to read and
to hand-edit as Cypher. Customer and circuit nodes are created here so they
stay consistent with what PostgreSQL generated in the same run.
"""

from __future__ import annotations

import os
from pathlib import Path

from common import DEVICE_BY_ID, step
from neo4j import GraphDatabase

import embed

SEED_DIR = Path("/seed/neo4j")


def _driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "neo4j_dev_password"),
        ),
    )


def _split_statements(text: str) -> list[str]:
    """Split a Cypher file on semicolons, ignoring comment-only fragments.

    The driver executes one statement per call, unlike cypher-shell which
    accepts a whole script.
    """
    statements = []
    for raw in text.split(";"):
        lines = [
            ln for ln in raw.splitlines()
            if ln.strip() and not ln.strip().startswith("//")
        ]
        if lines:
            statements.append("\n".join(lines))
    return statements


def seed(purge: bool = False) -> dict:
    counts = {"devices": 0, "interfaces": 0, "circuits": 0, "customers": 0, "embedded": 0}

    with _driver() as driver, driver.session() as session:
        if purge:
            step("purging existing graph")
            session.run("MATCH (n) DETACH DELETE n")

        # ---------- topology and indexes from Cypher files ----------
        for path in sorted(SEED_DIR.glob("*.cypher")):
            step(f"running {path.name}")
            for statement in _split_statements(path.read_text(encoding="utf-8")):
                session.run(statement)

        # ---------- customers and circuits ----------
        # Mirrors what seed_postgres.py inserted. Kept in the graph so a
        # question like "who is affected if this device goes down" can be
        # answered in a single traversal.
        import psycopg

        dsn = (
            f"host={os.getenv('PG_HOST', 'postgres')} "
            f"dbname={os.getenv('PG_DATABASE', 'mplsdb')} "
            f"user={os.getenv('PG_USER', 'mpls')} "
            f"password={os.getenv('PG_PASSWORD', 'mpls_dev_password')}"
        )
        with psycopg.connect(dsn) as conn:
            cur = conn.cursor()
            cur.execute("SELECT customer_id, name, segment FROM customers")
            customers = cur.fetchall()
            cur.execute(
                """SELECT circuit_id, customer_id, device_id, if_name,
                          service_type, bandwidth_mbps
                   FROM circuits"""
            )
            circuits = cur.fetchall()

        for customer_id, name, segment in customers:
            session.run(
                """MERGE (c:Customer {customer_id: $id})
                   SET c.name = $name, c.segment = $segment""",
                id=customer_id, name=name, segment=segment,
            )
            counts["customers"] += 1

        for circuit_id, customer_id, device_id, if_name, service_type, bw in circuits:
            session.run(
                """MATCH (cust:Customer {customer_id: $cust})
                   MATCH (d:Device {device_id: $dev})
                   MERGE (c:Circuit {circuit_id: $cid})
                     SET c.service_type = $stype,
                         c.bandwidth_mbps = $bw,
                         c.if_name = $ifname,
                         c.profile_text = $profile
                   MERGE (cust)-[:OWNS]->(c)
                   MERGE (c)-[:SERVED_BY]->(d)""",
                cust=customer_id, dev=device_id, cid=circuit_id,
                stype=service_type, bw=bw, ifname=if_name,
                profile=f"{service_type} circuit {circuit_id} at {bw} Mbps "
                        f"terminating on {device_id} interface {if_name}",
            )
            counts["circuits"] += 1

        # ---------- device profile text ----------
        # A short natural-language description per device. This is what gets
        # embedded, so semantic device lookup can work on meaning rather than
        # on the naming convention alone.
        for device_id, dev in DEVICE_BY_ID.items():
            role_text = {
                "CR": "core router carrying backbone transit between sites",
                "PE": "provider edge router terminating aggregation links and customer VRFs",
                "APE": "aggregation provider edge collecting traffic from local access routers",
                "LPE": "local provider edge terminating customer access circuits",
            }[dev["role"]]
            profile = (
                f"{device_id} is a {role_text}. "
                f"Located at site {dev['site']}. "
                f"Management address {dev['mgmt']}. "
                f"Interfaces: {', '.join(dev['ifaces'])}."
            )
            session.run(
                "MATCH (d:Device {device_id: $id}) SET d.profile_text = $p",
                id=device_id, p=profile,
            )
            counts["devices"] += 1

        result = session.run("MATCH (:Device)-[:HAS_INTERFACE]->(i:Interface) RETURN count(i) AS n")
        counts["interfaces"] = result.single()["n"]

        # ---------- vectors ----------
        if embed.is_available():
            step("generating device and circuit embeddings")
            records = session.run(
                "MATCH (d:Device) RETURN d.device_id AS id, d.profile_text AS text"
            ).data()
            vectors = embed.embed_many([r["text"] for r in records])
            if vectors:
                for record, vec in zip(records, vectors):
                    session.run(
                        "MATCH (d:Device {device_id: $id}) SET d.embedding = $vec",
                        id=record["id"], vec=vec,
                    )
                    counts["embedded"] += 1

            records = session.run(
                "MATCH (c:Circuit) RETURN c.circuit_id AS id, c.profile_text AS text"
            ).data()
            vectors = embed.embed_many([r["text"] for r in records])
            if vectors:
                for record, vec in zip(records, vectors):
                    session.run(
                        "MATCH (c:Circuit {circuit_id: $id}) SET c.embedding = $vec",
                        id=record["id"], vec=vec,
                    )
                    counts["embedded"] += 1

    return counts
