#!/usr/bin/env python3
"""Summarise open tickets. Runnable only through the MCP allowlist.

Kept deliberately simple and read-only: it opens a connection with the
read-only account, prints a table, and exits.
"""

from __future__ import annotations

import os

import psycopg


def main() -> None:
    dsn = os.getenv("PG_DSN", "postgresql://mcp_reader:mcp_reader_password@localhost:5432/mplsdb")
    with psycopg.connect(dsn) as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT severity, count(*) FROM tickets
               WHERE status <> 'closed' GROUP BY severity ORDER BY severity"""
        )
        print("Open tickets by severity")
        print("-" * 34)
        for severity, count in cur.fetchall():
            print(f"  {severity:<12} {count:>4}")

        cur.execute(
            """SELECT device_id, count(*) FROM tickets
               WHERE status <> 'closed' AND device_id IS NOT NULL
               GROUP BY device_id ORDER BY count(*) DESC LIMIT 10"""
        )
        print("\nOpen tickets by device")
        print("-" * 34)
        for device, count in cur.fetchall():
            print(f"  {device:<14} {count:>4}")


if __name__ == "__main__":
    main()
