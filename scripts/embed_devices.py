#!/usr/bin/env python3
"""Backfill device profile embeddings in Neo4j.

    make embed-devices

Neo4j 5 has native vector indexes. The reason this project embeds devices at
all - rather than relying only on pgvector and OpenSearch - is that Neo4j is
the only store where a semantic hit can be followed by a graph traversal in
the same query.
"""

import os
import sys

import httpx
from neo4j import GraphDatabase

# 1. บังคับชี้ไปที่ OpenRouter และใส่ API Key
EMBEDDING_BASE_URL = "https://openrouter.ai/api/v1"
EMBEDDING_MODEL = "openai/text-embedding-3-small"
API_KEY = ""

def embed_batch(texts: list[str]) -> list[list[float]]:
    response = httpx.post(
        f"{EMBEDDING_BASE_URL.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {API_KEY}"}, # 2. เพิ่ม Header เพื่อยืนยันตัวตน
        json={"model": EMBEDDING_MODEL, "input": texts},
        timeout=90,
    )
    response.raise_for_status()
    ordered = sorted(response.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in ordered]

def main() -> int:
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"),
              os.getenv("NEO4J_PASSWORD", "neo4j_dev_password")),
    )
    with driver, driver.session() as session:
        for label, key in (("Device", "device_id"), ("Circuit", "circuit_id")):
            records = session.run(
                f"MATCH (n:{label}) WHERE n.profile_text IS NOT NULL "
                f"RETURN n.{key} AS id, n.profile_text AS text"
            ).data()
            if not records:
                print(f"  no {label} nodes with profile_text - run `make seed` first")
                continue

            vectors = embed_batch([r["text"] for r in records])
            for record, vector in zip(records, vectors):
                session.run(
                    f"MATCH (n:{label} {{{key}: $id}}) SET n.embedding = $vec",
                    id=record["id"], vec=vector,
                )
            print(f"  embedded {len(records)} {label} nodes")

        count = session.run(
            "MATCH (n) WHERE n.embedding IS NOT NULL RETURN count(n) AS n"
        ).single()["n"]
        print(f"\n  {count} nodes now carry embeddings\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
