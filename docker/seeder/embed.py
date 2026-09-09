"""Embedding client with graceful degradation.

The seeder tries to populate vector columns so the demo works immediately
after `make up`. But the embedding endpoint may not be reachable yet - a
laptop without the llm profile running, a gateway behind VPN, a GPU server
still booting.

When that happens the seeder must NOT fail. It writes NULL vectors, prints
a clear warning, and tells the operator to run `make embed-tickets` later.
A workshop where `make up` fails because a model is missing is a workshop
that loses its first hour.
"""

from __future__ import annotations

import os

import httpx

EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://host.docker.internal:11434/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "embeddinggemma:300m")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
TIMEOUT = float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "30"))

_available: bool | None = None


def is_available() -> bool:
    """Probe the endpoint once and cache the result."""
    global _available
    if _available is not None:
        return _available
    try:
        vec = embed_one("probe")
        _available = vec is not None
    except Exception:
        _available = False
    if not _available:
        print(
            "\n  !! Embedding endpoint not reachable at "
            f"{EMBEDDING_BASE_URL}\n"
            "     Vector columns will be left empty. Everything else still works.\n"
            "     Backfill later with:  make embed-tickets && make embed-devices\n",
            flush=True,
        )
    return _available


def embed_one(text: str) -> list[float] | None:
    """Embed a single string. Returns None on any failure."""
    result = embed_many([text])
    return result[0] if result else None


def embed_many(texts: list[str]) -> list[list[float]] | None:
    """Embed a batch of strings through the OpenAI-compatible embeddings API.

    Ollama, vLLM and most internal gateways all speak this shape, which is
    why the workshop never needs a provider-specific client.
    """
    if not texts:
        return []
    try:
        response = httpx.post(
            f"{EMBEDDING_BASE_URL.rstrip('/')}/embeddings",
            json={"model": EMBEDDING_MODEL, "input": texts},
            headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', 'not-needed')}"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()["data"]
        # The API does not guarantee ordering, so sort by index.
        ordered = sorted(data, key=lambda d: d["index"])
        vectors = [d["embedding"] for d in ordered]
        for v in vectors:
            if len(v) != EMBEDDING_DIM:
                raise ValueError(
                    f"Model returned {len(v)} dimensions but EMBEDDING_DIM is "
                    f"{EMBEDDING_DIM}. Fix EMBEDDING_DIM in .env, and remember the "
                    f"pgvector column and the OpenSearch mapping must match too."
                )
        return vectors
    except Exception as exc:  # noqa: BLE001 - degradation is the whole point
        print(f"     embedding request failed: {type(exc).__name__}: {exc}", flush=True)
        return None
