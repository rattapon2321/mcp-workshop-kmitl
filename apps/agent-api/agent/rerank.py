"""Rerank retrieved passages with a cross-encoder.

Why a second model when the embeddings already ranked things
------------------------------------------------------------
An embedding model encodes the query and the document separately and compares
vectors. It never sees the two together. A cross-encoder reads the pair and
scores the actual relationship, which is why a retrieve-then-rerank pipeline
beats retrieve-alone on the same corpus.

The practical shape is: retrieve widely (50), rerank, keep few (5). Sending
fewer, better passages to the main model reduces hallucination more reliably
than sending more passages, because irrelevant context actively misleads.

This mirrors the production pipeline:
    EmbeddingGemma 300M -> mxbai-rerank -> main model
"""

from __future__ import annotations

import os

import httpx

RERANK_BASE_URL = os.getenv("RERANK_BASE_URL", "http://localhost:7997")
RERANK_MODEL = os.getenv("RERANK_MODEL", "mixedbread-ai/mxbai-rerank-base-v2")
TOP_K = int(os.getenv("RERANK_TOP_K", "5"))


async def rerank(query: str, passages: list[dict], top_k: int | None = None,
                 text_field: str = "content") -> list[dict]:
    """Reorder passages by relevance to the query.

    Falls back to the original order when the rerank service is unavailable,
    truncated to top_k. Degrading to "the embedding order" is acceptable;
    failing the whole request because a reranker is down is not.
    """
    top_k = top_k or TOP_K
    if not passages:
        return []

    documents = [p.get(text_field, "") for p in passages]
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{RERANK_BASE_URL.rstrip('/')}/rerank",
                json={"model": RERANK_MODEL, "query": query,
                      "documents": documents, "top_n": top_k},
            )
            response.raise_for_status()
            data = response.json()
    except Exception:  # noqa: BLE001
        for passage in passages[:top_k]:
            passage["rerank_status"] = "unavailable"
        return passages[:top_k]

    ranked = []
    for item in data.get("results", []):
        index = item.get("index")
        if index is None or index >= len(passages):
            continue
        passage = dict(passages[index])
        passage["rerank_score"] = item.get("relevance_score")
        passage["rerank_status"] = "ok"
        ranked.append(passage)

    return ranked[:top_k] if ranked else passages[:top_k]
