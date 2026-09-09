#!/usr/bin/env python3
"""Incident counts and top affected devices for a relative time range.

Demonstrates a script that accepts a parameter. The parameter is validated
against a fixed set - a script exposed through MCP must never accept a value
that could widen what it does.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone

import psycopg

RANGES = {"last_24h": 1, "last_7d": 7, "last_14d": 14, "last_30d": 30}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--range", default="last_7d", choices=sorted(RANGES))
    args = parser.parse_args()

    days = RANGES[args.range]
    since = datetime.now(timezone(timedelta(hours=7))) - timedelta(days=days)

    dsn = os.getenv("PG_DSN", "postgresql://mcp_reader:mcp_reader_password@localhost:5432/mplsdb")
    with psycopg.connect(dsn) as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT category, severity, count(*) FROM tickets
               WHERE opened_at >= %s AND category <> 'maintenance'
               GROUP BY category, severity ORDER BY count(*) DESC""",
            (since,),
        )
        print(f"Incidents in the {args.range.replace('last_', 'last ')}")
        print("-" * 46)
        for category, severity, count in cur.fetchall():
            print(f"  {category:<14}{severity:<10}{count:>4}")

        cur.execute(
            """SELECT device_id, count(*) FROM tickets
               WHERE opened_at >= %s AND device_id IS NOT NULL
                 AND category <> 'maintenance'
               GROUP BY device_id ORDER BY count(*) DESC LIMIT 5""",
            (since,),
        )
        print("\nMost affected devices")
        print("-" * 46)
        for device, count in cur.fetchall():
            print(f"  {device:<16}{count:>4}")


if __name__ == "__main__":
    main()
