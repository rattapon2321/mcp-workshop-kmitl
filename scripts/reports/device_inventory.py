#!/usr/bin/env python3
"""List every device with site, role and how many circuits terminate on it."""

from __future__ import annotations

import os

import psycopg


def main() -> None:
    dsn = os.getenv("PG_DSN", "postgresql://mcp_reader:mcp_reader_password@localhost:5432/mplsdb")
    with psycopg.connect(dsn) as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT d.device_id, d.site_code, d.role, d.model,
                      count(c.circuit_id) AS circuits
               FROM devices d
               LEFT JOIN circuits c ON c.device_id = d.device_id
               GROUP BY d.device_id, d.site_code, d.role, d.model
               ORDER BY d.site_code, d.role, d.device_id"""
        )
        print(f"{'device':<14}{'site':<6}{'role':<6}{'model':<14}{'circuits':>9}")
        print("-" * 50)
        for device, site, role, model, circuits in cur.fetchall():
            print(f"{device:<14}{site:<6}{role:<6}{model:<14}{circuits:>9}")


if __name__ == "__main__":
    main()
