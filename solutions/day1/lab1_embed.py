#!/usr/bin/env python3
"""Lab 1 reference solution: build the vector column from scratch.

    python solutions/day1/lab1_embed.py

Covers all five steps of the lab:
    1. add the column
    2. generate embeddings in batches
    3. backfill every row
    4. create the HNSW index AFTER backfilling
    5. verify and run a search

Three mistakes cost participants the most time. Each is marked below with
"PITFALL" and explained where it happens rather than in a list at the top,
because the reason only makes sense next to the code that causes it.
"""

from __future__ import annotations

import os
import sys
import time
from dotenv import load_dotenv
load_dotenv()

import httpx
import psycopg

PG_DSN = os.getenv("PG_ADMIN_DSN",
                   "postgresql://mpls:mpls_dev_password@localhost:5432/mplsdb")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://openrouter.ai/api/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))  # text-embedding-3-small มี 1536 dimensions

BATCH_SIZE = 32


# --------------------------------------------------------------------------
# Step 2: embedding
# --------------------------------------------------------------------------

def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of strings through the OpenAI-compatible endpoint."""
    response = httpx.post(
        f"{EMBEDDING_BASE_URL.rstrip('/')}/embeddings",
        json={"model": EMBEDDING_MODEL, "input": texts},
        headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', 'not-needed')}"},
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()["data"]

    # PITFALL 1 - the silent one.
    # The API returns a list of {index, embedding}. Nothing in the spec
    # promises that list is in request order, and some gateways reorder under
    # concurrency. Zipping the raw list against the input pairs vectors with
    # the WRONG rows, and nothing fails: searches simply return nonsense, and
    # the cause is invisible because every row has a valid-looking vector.
    ordered = sorted(data, key=lambda d: d["index"])
    vectors = [d["embedding"] for d in ordered]

    if vectors and len(vectors[0]) != EMBEDDING_DIM:
        raise SystemExit(
            f"Model returned {len(vectors[0])} dimensions, but the column is "
            f"vector({EMBEDDING_DIM}). Both must match, and so must the "
            f"OpenSearch mapping and the Neo4j index."
        )
    return vectors


# --------------------------------------------------------------------------
# Steps 1-5
# --------------------------------------------------------------------------

def add_column(cur) -> None:
    """Step 1. 1536 is not arbitrary - it is EmbeddingGemma's output size."""
    cur.execute(f"ALTER TABLE tickets ADD COLUMN IF NOT EXISTS embedding vector({EMBEDDING_DIM})")
    print(f"  column ready: tickets.embedding vector({EMBEDDING_DIM})")


def backfill(conn, cur) -> int:
    """Steps 2-3."""
    # PITFALL 2 - embed title AND description.
    # The title is a one-line summary written in a hurry; the description is
    # where the symptom actually lives. Embedding the title alone measurably
    # reduces what semantic search can find.
    cur.execute("SELECT ticket_id, title, description FROM tickets ORDER BY ticket_id")
    rows = cur.fetchall()

    print(f"  embedding {len(rows)} tickets in batches of {BATCH_SIZE}")
    started = time.time()
    done = 0

    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]

        # PITFALL 3 - batch, do not loop one row at a time.
        # One HTTP round trip per ticket turns a 20-second job into several
        # minutes, and the cost is entirely network latency, not compute.
        vectors = embed_batch([f"{title}\n\n{description}"
                               for _, title, description in chunk])

        for (ticket_id, _, _), vector in zip(chunk, vectors):
            # psycopg sends the vector as a string literal; pgvector parses it.
            cur.execute("UPDATE tickets SET embedding = %s WHERE ticket_id = %s",
                        (str(vector), ticket_id))

        conn.commit()
        done += len(chunk)
        print(f"    {done}/{len(rows)}")

    print(f"  finished in {time.time() - started:.1f}s")
    return done


def create_index(cur) -> None:
    """Step 4.

    Build the index AFTER the data is in place. HNSW built on an empty table
    and then filled row by row produces a worse-connected graph and takes
    longer overall.

    vector_cosine_ops, not vector_l2_ops: embedding models are trained so that
    semantic similarity corresponds to the ANGLE between vectors. Using L2 on
    the same data gives visibly worse ranking.
    """
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_tickets_embedding ON tickets
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    print("  HNSW index created (cosine)")


def verify(cur) -> bool:
    """Step 5a."""
    cur.execute("SELECT count(*), count(embedding) FROM tickets")
    total, embedded = cur.fetchone()
    print(f"  {embedded}/{total} tickets have embeddings")
    return embedded == total


def search(cur, query: str, limit: int = 5) -> None:
    """Step 5b. `<=>` is cosine distance: smaller is closer."""
    vector = embed_batch([query])[0]
    cur.execute(
        """SELECT ticket_id, category, title, embedding <=> %s::vector AS distance
           FROM tickets
           WHERE embedding IS NOT NULL
           ORDER BY embedding <=> %s::vector
           LIMIT %s""",
        (str(vector), str(vector), limit),
    )
    print(f"\n  ค้นหา: {query}")
    for ticket_id, category, title, distance in cur.fetchall():
        print(f"    {distance:.4f}  {ticket_id}  [{category}]  {title[:52]}")


def compare_with_keyword(cur, query: str) -> None:
    """Bonus: show what keyword search misses.

    This is the exercise that makes the value of embeddings concrete. A
    customer writes "เน็ตหลุด"; an engineer writes "circuit drop". No amount
    of LIKE matching bridges that gap.
    """
    cur.execute(
        "SELECT ticket_id, title FROM tickets WHERE title ILIKE %s LIMIT 5",
        (f"%{query}%",),
    )
    rows = cur.fetchall()
    print(f"\n  keyword ILIKE '%{query}%' -> {len(rows)} รายการ")
    for ticket_id, title in rows:
        print(f"    {ticket_id}  {title[:60]}")
    if not rows:
        print("    (ไม่พบเลย - นี่คือจุดที่ semantic search ชนะ)")


def main() -> int:
    print("\n=== Lab 1: สร้าง vector column ด้วยตัวเอง ===\n")

    with psycopg.connect(PG_DSN) as conn:
        cur = conn.cursor()

        add_column(cur)
        conn.commit()

        backfill(conn, cur)
        create_index(cur)
        conn.commit()

        if not verify(cur):
            print("  WARNING: some tickets are still missing embeddings")

        search(cur, "ลูกค้าบ่นว่าอินเทอร์เน็ตหลุดบ่อย")
        search(cur, "adjacency ไม่ขึ้นหลังเปลี่ยนอุปกรณ์")
        compare_with_keyword(cur, "circuit drop")

    print("\n  เสร็จแล้ว ลองถามใน Chainlit: "
          "'เคยมีเคสเน็ตหลุดเป็นช่วงๆ ไหม'\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
