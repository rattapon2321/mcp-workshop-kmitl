#!/usr/bin/env python3
"""Seed all three databases for the AI x IP-MPLS workshop.

Run automatically by `make up`, or manually:

    make seed        add data, keep what is already there
    make reseed      purge first, so timestamps become fresh again

Read this file. It is intentionally written to be read: the workshop asks
participants to understand where every row in the dataset comes from, and
the scenarios in data/scenarios.md only make sense if the seeding logic
that produces them is legible.
"""

from __future__ import annotations

import argparse
import sys

from common import anchor_now, banner, load_scenarios, step

import seed_neo4j
import seed_opensearch
import seed_postgres


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the workshop dataset")
    parser.add_argument(
        "--purge",
        action="store_true",
        help="delete existing data first (use before a demo so timestamps are fresh)",
    )
    args = parser.parse_args()

    banner("AI x IP-MPLS workshop - seeding")
    print(f"  anchor time : {anchor_now().isoformat()}")
    print("  every timestamp below is generated as an offset from this anchor,")
    print("  which is why the dataset never goes stale. See data/scenarios.md #7.")

    scenarios = load_scenarios()
    print(f"  scenarios   : {', '.join(s['id'] for s in scenarios)}")

    banner("PostgreSQL - tickets, circuits, customers")
    pg = seed_postgres.seed(scenarios, purge=args.purge)
    for key, value in pg.items():
        step(f"{key:<12} {value}")

    banner("Neo4j - topology, circuits, vectors")
    neo = seed_neo4j.seed(purge=args.purge)
    for key, value in neo.items():
        step(f"{key:<12} {value}")

    banner("OpenSearch - logs and embedded documents")
    os_counts = seed_opensearch.seed(scenarios, purge=args.purge)
    for key, value in os_counts.items():
        step(f"{key:<12} {value}")

    banner("Done")
    print("  Verify with:  make verify")
    if not pg.get("embedded"):
        print()
        print("  NOTE: vector columns are empty because the embedding endpoint")
        print("        was unreachable. Everything else works. Backfill later:")
        print("          make embed-tickets && make embed-devices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
