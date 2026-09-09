"""Define "now" from the data, not from the wall clock.

Why this module exists
----------------------
A dataset seeded three weeks before a demo answers nothing when the question
is "what happened in the last 24 hours". And an LLM has no reliable idea what
today's date is, so letting the model compute date ranges produces confident,
wrong filters.

Both problems disappear if the system has one definition of "now" that comes
from the data itself, and if tools accept relative ranges rather than dates.

Resolution order:
    1. DEMO_NOW environment variable  - pinned, used by tests
    2. newest @timestamp in the log index - the normal case

The value is also published as the MCP resource `clock://now`, so the model
can read what the system considers current before it plans anything.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from config import settings

BANGKOK = timezone(timedelta(hours=7))

_CACHE: tuple[datetime, float] | None = None
_CACHE_TTL_SECONDS = 300

# Relative ranges the tools accept. Absolute dates are deliberately not
# supported: every date an LLM invents is a date it can get wrong.
RANGES: dict[str, timedelta] = {
    "last_1h": timedelta(hours=1),
    "last_6h": timedelta(hours=6),
    "last_24h": timedelta(hours=24),
    "last_3d": timedelta(days=3),
    "last_7d": timedelta(days=7),
    "last_14d": timedelta(days=14),
    "last_30d": timedelta(days=30),
    "last_90d": timedelta(days=90),
}


def _newest_log_timestamp() -> datetime | None:
    try:
        from opensearchpy import OpenSearch

        client = OpenSearch(hosts=[settings().opensearch_url], timeout=10)
        hits = client.search(
            index=f"{settings().log_index}-*",
            body={"size": 1, "sort": [{"@timestamp": "desc"}], "_source": ["@timestamp"]},
        )["hits"]["hits"]
        if hits:
            return datetime.fromisoformat(hits[0]["_source"]["@timestamp"])
    except Exception:  # noqa: BLE001 - fall through to wall clock
        return None
    return None


def data_now(refresh: bool = False) -> datetime:
    """The timestamp the whole system treats as the present moment."""
    global _CACHE

    pinned = settings().demo_now.strip()
    if pinned:
        return datetime.fromisoformat(pinned).astimezone(BANGKOK)

    if _CACHE and not refresh and (time.time() - _CACHE[1]) < _CACHE_TTL_SECONDS:
        return _CACHE[0]

    resolved = _newest_log_timestamp() or datetime.now(BANGKOK)
    _CACHE = (resolved, time.time())
    return resolved


def resolve_range(name: str) -> tuple[datetime, datetime]:
    """Turn a relative range name into concrete start and end timestamps."""
    if name not in RANGES:
        raise ValueError(
            f"Unknown range '{name}'. Use one of: {', '.join(RANGES)}. "
            "Absolute dates are not accepted - the data window moves, "
            "so relative ranges are the only reliable way to ask."
        )
    end = data_now()
    return end - RANGES[name], end


def coverage() -> dict:
    """What the model should know about the data window before planning."""
    now = data_now()
    return {
        "data_now": now.isoformat(),
        "data_range": {
            "from": (now - RANGES["last_30d"]).isoformat(),
            "to": now.isoformat(),
        },
        "ticket_history_days": 90,
        "log_retention_days": 30,
        "accepted_ranges": list(RANGES),
        "note": (
            "'now' is defined by the newest log record, not by the server clock. "
            "Anything outside data_range does not exist in this system: say so "
            "rather than estimating."
        ),
    }
