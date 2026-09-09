"""Database connections shared by all tools.

Connections are created lazily and reused. Every accessor here returns a
read-only handle: there is no code path in this server that writes.
"""

from __future__ import annotations

from functools import lru_cache

import httpx
import psycopg
from config import settings
from neo4j import GraphDatabase
from opensearchpy import OpenSearch
from psycopg.rows import dict_row


@lru_cache
def neo4j_driver():
    return GraphDatabase.driver(
        settings().neo4j_uri,
        auth=(settings().neo4j_user, settings().neo4j_password),
        connection_timeout=10,
    )


@lru_cache
def opensearch() -> OpenSearch:
    return OpenSearch(
        hosts=[settings().opensearch_url],
        http_compress=True,
        timeout=settings().query_timeout_seconds,
    )


def pg_query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a parameterised read query and return dict rows.

    Parameters are always bound, never interpolated. Even though the account
    is read-only, string interpolation would still allow data exfiltration
    through a crafted predicate.
    """
    with psycopg.connect(settings().pg_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = '{settings().query_timeout_seconds}s'")
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def neo4j_query(cypher: str, **params) -> list[dict]:
    with neo4j_driver().session() as session:
        result = session.run(cypher, **params)
        return [record.data() for record in result]


def embed_query(text: str) -> list[float] | None:
    """Embed a search string. Returns None if the endpoint is unavailable,
    so callers can fall back to keyword search instead of failing."""
    try:
        response = httpx.post(
            f"{settings().embedding_base_url.rstrip('/')}/embeddings",
            json={"model": settings().embedding_model, "input": [text]},
            headers={"Authorization": f"Bearer {settings().llm_api_key}"},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]
    except Exception:  # noqa: BLE001
        return None
