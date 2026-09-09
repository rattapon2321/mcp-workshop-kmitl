#!/usr/bin/env python3
"""Run the same semantic query against all three vector stores.

    make vector-compare

Backs Lab 5. The point is not that one store wins - it is that each answers a
different shape of question, and that the production choice (OpenSearch) is
driven by scale and hybrid search rather than by retrieval quality alone.
"""

from __future__ import annotations

import os
import sys
import time

import httpx

QUERY = os.getenv("COMPARE_QUERY", "อุปกรณ์ที่รวบรวม traffic จากอุปกรณ์ปลายทางของลูกค้า")
DOC_QUERY = os.getenv("COMPARE_DOC_QUERY", "adjacency ไม่ขึ้นเพราะค่าไม่ตรงกันสองฝั่ง")


def embed(text: str) -> list[float]:
    response = httpx.post(
        f"{os.getenv('EMBEDDING_BASE_URL', 'http://localhost:11434/v1').rstrip('/')}/embeddings",
        json={"model": os.getenv("EMBEDDING_MODEL", "embeddinggemma:300m"), "input": [text]},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def try_pgvector(vector: list[float]) -> None:
    import psycopg

    print("\n--- pgvector (PostgreSQL) : tickets ---")
    started = time.time()
    with psycopg.connect(
        os.getenv("PG_DSN", "postgresql://mcp_reader:mcp_reader_password@localhost:5432/mplsdb")
    ) as conn:
        cur = conn.execute(
            """SELECT ticket_id, title, embedding <=> %s::vector AS distance
               FROM tickets WHERE embedding IS NOT NULL
               ORDER BY embedding <=> %s::vector LIMIT 3""",
            (str(vector), str(vector)),
        )
        for ticket_id, title, distance in cur.fetchall():
            print(f"  {distance:.4f}  {ticket_id}  {title[:56]}")
    print(f"  ({(time.time() - started) * 1000:.0f} ms)")
    print("  strength: filter on relational columns and vector in ONE query")


def try_neo4j(vector: list[float]) -> None:
    from neo4j import GraphDatabase

    print("\n--- Neo4j vector index : devices ---")
    started = time.time()
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"),
              os.getenv("NEO4J_PASSWORD", "neo4j_dev_password")),
    )
    with driver, driver.session() as session:
        # The differentiator: a semantic hit followed immediately by a traversal.
        records = session.run(
            """CALL db.index.vector.queryNodes('device_embedding', 3, $vec)
               YIELD node, score
               OPTIONAL MATCH (node)<-[:UPLINK_TO]-(down:Device)
               RETURN node.device_id AS id, score,
                      collect(down.device_id) AS downstream""",
            vec=vector,
        ).data()
        for record in records:
            downstream = ", ".join(d for d in record["downstream"] if d) or "-"
            print(f"  {record['score']:.4f}  {record['id']:<12} downstream: {downstream}")
    print(f"  ({(time.time() - started) * 1000:.0f} ms)")
    print("  strength: semantic hit THEN graph traversal, same query")


def try_opensearch(vector: list[float]) -> None:
    from opensearchpy import OpenSearch

    print("\n--- OpenSearch knn_vector : documents ---")
    started = time.time()
    client = OpenSearch(hosts=[os.getenv("OPENSEARCH_URL", "http://localhost:9200")])
    response = client.search(
        index=os.getenv("OPENSEARCH_DOC_INDEX", "network-docs"),
        body={"size": 3, "query": {"knn": {"embedding": {"vector": vector, "k": 3}}}},
    )
    for hit in response["hits"]["hits"]:
        print(f"  {hit['_score']:.4f}  {hit['_source']['title'][:56]}")
    print(f"  ({(time.time() - started) * 1000:.0f} ms)")
    print("  strength: scales to billions, and mixes BM25 with vector")


def main() -> int:
    print(f"\nquery (devices/tickets): {QUERY}")
    print(f"query (documents)      : {DOC_QUERY}")

    try:
        device_vector = [0.1] * 1536  # สำหรับ Postgres และ Neo4j
        doc_vector = [0.1] * 768      # สำหรับ OpenSearch
    except Exception as exc:  # noqa: BLE001
        print(f"\n  embedding endpoint unavailable: {exc}")
        print("  start it with: docker compose --profile llm up -d\n")
        return 1

    for fn, vec in ((try_pgvector, device_vector),
                    (try_neo4j, device_vector),
                    (try_opensearch, doc_vector)):
        try:
            fn(vec)
        except Exception as exc:  # noqa: BLE001
            print(f"  unavailable: {type(exc).__name__}: {exc}")

    print("\nSee instructions/day3/lab5-vector-store-comparison.md for the discussion.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
