"""Long-term memory backed by pgvector.

Short-term memory forgets on purpose. Long-term memory is what survives:
facts worth carrying between sessions, stored as embeddings and recalled by
meaning rather than by keyword.

This deliberately reuses the same vector column participants build in Lab 1,
which is the point - the embedding work from day one becomes the memory
substrate on day two.

Kept in its own table so a reset of the workshop dataset does not wipe it,
and so participants can inspect exactly what the agent chose to remember.
"""

from __future__ import annotations

import os

import httpx
import psycopg

PG_DSN = os.getenv(
    "PG_ADMIN_DSN",
    "postgresql://mpls:mpls_dev_password@localhost:5432/mplsdb",
)
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "embeddinggemma:300m")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

DDL = f"""
CREATE TABLE IF NOT EXISTS agent_memory (
    id          SERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- fact | preference | conclusion
    content     TEXT NOT NULL,
    entities    TEXT[] DEFAULT '{{}}',
    embedding   vector({EMBEDDING_DIM}),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_memory_session ON agent_memory(session_id);
"""


def _embed(text: str) -> list[float] | None:
    try:
        response = httpx.post(
            f"{EMBEDDING_BASE_URL.rstrip('/')}/embeddings",
            json={"model": EMBEDDING_MODEL, "input": [text]},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]
    except Exception:  # noqa: BLE001
        return None


def ensure_schema() -> None:
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(DDL)
        conn.commit()


def remember(session_id: str, content: str, kind: str = "conclusion",
             entities: list[str] | None = None) -> bool:
    """Store one fact. Returns False if the embedding endpoint is unavailable."""
    vector = _embed(content)
    if vector is None:
        return False
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            """INSERT INTO agent_memory (session_id, kind, content, entities, embedding)
               VALUES (%s, %s, %s, %s, %s)""",
            (session_id, kind, content, entities or [], str(vector)),
        )
        conn.commit()
    return True


def recall(query: str, limit: int = 3, session_id: str | None = None) -> list[dict]:
    """Retrieve facts related to a query by meaning.

    Recall is not scoped to the current session by default: a conclusion
    reached last week about a device is still useful today.
    """
    vector = _embed(query)
    if vector is None:
        return []
    where = "WHERE embedding IS NOT NULL"
    params: list = [str(vector)]
    if session_id:
        where += " AND session_id = %s"
        params.append(session_id)
    params.append(str(vector))
    params.append(limit)

    with psycopg.connect(PG_DSN) as conn:
        cur = conn.execute(
            f"""SELECT content, kind, entities, created_at,
                       embedding <=> %s::vector AS distance
                FROM agent_memory {where}
                ORDER BY embedding <=> %s::vector
                LIMIT %s""",
            tuple(params),
        )
        return [
            {"content": row[0], "kind": row[1], "entities": row[2],
             "created_at": row[3], "distance": float(row[4])}
            for row in cur.fetchall()
        ]
