"""Shared helpers for the seeder.

The single most important idea in this module is `anchor_now()`.

Everything time-related in the dataset is generated as an offset from one
anchor timestamp captured at seed time. Nothing is hardcoded to a calendar
date, so the dataset is always "fresh" relative to whenever it was seeded,
and `make reseed` on the morning of a demo is enough to make questions like
"in the last 24 hours" work again.

See data/scenarios.md section 7 for the full reasoning.
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

BANGKOK = timezone(timedelta(hours=7))

SCENARIO_DIR = Path(__file__).parent / "scenarios"

# Deterministic by default so tests and evaluations compare like with like.
RANDOM_SEED = int(os.getenv("SEED_RANDOM_SEED", "42"))
DAYS_BACK = int(os.getenv("SEED_DAYS_BACK", "30"))

rng = random.Random(RANDOM_SEED)

_ANCHOR: datetime | None = None


def anchor_now() -> datetime:
    """Return the single reference timestamp for this seeding run.

    Captured once and reused, so every store agrees on what "now" means.
    DEMO_NOW pins it explicitly, which is how tests get reproducible data.
    """
    global _ANCHOR
    if _ANCHOR is None:
        pinned = os.getenv("DEMO_NOW", "").strip()
        if pinned:
            _ANCHOR = datetime.fromisoformat(pinned).astimezone(BANGKOK)
        else:
            _ANCHOR = datetime.now(BANGKOK).replace(microsecond=0)
    return _ANCHOR


def hours_ago(h: float) -> datetime:
    """Convert an `hours_ago` offset into an absolute timestamp."""
    return anchor_now() - timedelta(hours=h)


def random_hours_ago(window: list[float]) -> float:
    """Pick a random offset inside a [start, end] hours-ago window."""
    start, end = window
    return rng.uniform(min(start, end), max(start, end))


def load_scenarios() -> list[dict]:
    """Load every scenario definition, baseline and filler first."""
    files = sorted(SCENARIO_DIR.glob("*.yaml"))
    return [yaml.safe_load(f.read_text(encoding="utf-8")) for f in files]


def weighted_choice(templates: list[dict]) -> dict:
    """Pick one template honouring the `weight` field."""
    weights = [t.get("weight", 1) for t in templates]
    return rng.choices(templates, weights=weights, k=1)[0]


# --------------------------------------------------------------------------
# Device inventory. Kept here rather than read back from PostgreSQL so the
# seeder can build Neo4j and OpenSearch even if Postgres is seeded later.
# Must stay in sync with docker/postgres/init/03_reference_data.sql.
# --------------------------------------------------------------------------

DEVICES = [
    {"id": "CR-BKK-01",  "site": "BKK", "role": "CR",  "mgmt": "10.10.0.1",
     "ifaces": ["Hu0/0/0/0", "Hu0/0/0/1", "Hu0/0/0/2"]},
    {"id": "CR-BKK-02",  "site": "BKK", "role": "CR",  "mgmt": "10.10.0.2",
     "ifaces": ["Hu0/0/0/0", "Te0/0/3"]},
    {"id": "PE-BKK-02",  "site": "BKK", "role": "PE",  "mgmt": "10.10.1.2",
     "ifaces": ["Hu0/1/0/0", "Te0/1/0/1", "Te0/1/0/2"]},
    {"id": "APE-BKK-05", "site": "BKK", "role": "APE", "mgmt": "10.10.2.5",
     "ifaces": ["Te0/1/1", "Ge0/2/1", "Ge0/2/2"]},
    {"id": "PE-NBI-01",  "site": "NBI", "role": "PE",  "mgmt": "10.20.1.1",
     "ifaces": ["Hu0/0/0/0", "Te0/0/1", "Te0/0/2"]},
    {"id": "PE-NBI-04",  "site": "NBI", "role": "PE",  "mgmt": "10.20.1.4",
     "ifaces": ["Te0/0/1", "Te0/0/2"]},
    {"id": "APE-NBI-03", "site": "NBI", "role": "APE", "mgmt": "10.20.2.3",
     "ifaces": ["Te0/1/2", "Ge0/2/1", "Ge0/2/2", "Ge0/2/3"]},
    {"id": "LPE-NBI-11", "site": "NBI", "role": "LPE", "mgmt": "10.20.3.11",
     "ifaces": ["Ge0/0/1", "Ge0/0/2", "Ge0/0/3"]},
    {"id": "LPE-NBI-12", "site": "NBI", "role": "LPE", "mgmt": "10.20.3.12",
     "ifaces": ["Ge0/0/1", "Ge0/0/2"]},
    {"id": "LPE-NBI-13", "site": "NBI", "role": "LPE", "mgmt": "10.20.3.13",
     "ifaces": ["Ge0/0/1", "Ge0/0/2", "Ge0/0/3"]},
]

DEVICE_BY_ID = {d["id"]: d for d in DEVICES}

# Devices that customers actually connect to.
ACCESS_DEVICES = [d["id"] for d in DEVICES if d["role"] in ("LPE", "APE")]


def log_line_defaults(device_id: str) -> dict:
    """Values used to fill placeholders in scenario message templates."""
    dev = DEVICE_BY_ID[device_id]
    return {
        "interface": rng.choice(dev["ifaces"]),
        "peer_ip": f"10.{rng.randint(10, 20)}.{rng.randint(0, 3)}.{rng.randint(1, 20)}",
        "octet": rng.randint(2, 250),
        "temp": rng.randint(28, 46),
        "cpu": rng.randint(71, 96),
        "crc_count": rng.randint(3, 480),
        "fan_rpm": rng.randint(2100, 3200),
    }


def banner(text: str) -> None:
    print(f"\n{'=' * 60}\n  {text}\n{'=' * 60}", flush=True)


def step(text: str) -> None:
    print(f"  - {text}", flush=True)
