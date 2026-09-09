#!/usr/bin/env python3
"""Backfill ticket embeddings in PostgreSQL.

Reference implementation for Lab 1. Participants write their own first;
this exists so a broken embedding endpoint does not block the rest of the day.

    make embed-tickets
"""

from __future__ import annotations

import os
import sys

import httpx
import psycopg

PG_DSN = os.getenv("PG_ADMIN_DSN",
                   "postgresql://mpls:mpls_dev_password@localhost:5432/mplsdb")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "embeddinggemma:300m")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
BATCH = 32


def embed_batch(texts: list[str]) -> list[list[float]]:
    response = httpx.post(
        f"{EMBEDDING_BASE_URL.rstrip('/')}/embeddings",
        json={"model": EMBEDDING_MODEL, "input": texts},
        headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', 'not-needed')}"},
        timeout=90,
    )
    response.raise_for_status()
    # Sort by index: the API does not promise to return items in request order,
    # and getting this wrong silently pairs vectors with the wrong rows.
    ordered = sorted(response.json()["data"], key=lambda d: d["index"])
    vectors = [d["embedding"] for d in ordered]
    if vectors and len(vectors[0]) != EMBEDDING_DIM:
        raise SystemExit(
            f"Model returned {len(vectors[0])} dimensions but EMBEDDING_DIM is "
            f"{EMBEDDING_DIM}. The pgvector column must match exactly."
        )
    return vectors


def main() -> int:
    with psycopg.connect(PG_DSN) as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT count(*) FROM information_schema.columns
               WHERE table_name='tickets' AND column_name='embedding'"""
        )
        if cur.fetchone()[0] == 0:
            print("\n  tickets.embedding does not exist yet.")
            print("  That is expected right after `make lab1-reset`.")
            print("  Add it first:  ALTER TABLE tickets ADD COLUMN embedding vector(768);\n")
            return 1

        cur.execute("SELECT ticket_id, title, description FROM tickets ORDER BY ticket_id")
        rows = cur.fetchall()
        print(f"\n  Embedding {len(rows)} tickets with {EMBEDDING_MODEL}")

        done = 0
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            vectors = embed_batch([f"{t}\n\n{d}" for _, t, d in chunk])
            for (ticket_id, _, _), vector in zip(chunk, vectors):
                cur.execute("UPDATE tickets SET embedding = %s WHERE ticket_id = %s",
                            (str(vector), ticket_id))
            conn.commit()
            done += len(chunk)
            print(f"    {done}/{len(rows)}")

        cur.execute("SELECT count(*), count(embedding) FROM tickets")
        total, embedded = cur.fetchone()
        print(f"\n  Done: {embedded}/{total} tickets have embeddings\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
