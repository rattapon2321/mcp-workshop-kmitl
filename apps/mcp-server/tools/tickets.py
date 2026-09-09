"""Ticket and configuration tools (PostgreSQL).

Tool descriptions here are written for a model, not for a developer.
Two rules produce most of the accuracy gain, and both are demonstrated below:

  1. Say when NOT to use the tool. Models pick the wrong tool far more often
     from a missing exclusion than from a vague description.
  2. Describe what the tool returns, not how it works internally.

Challenge 3 (day2) has participants rewrite bad descriptions and measure the
improvement with tests/test_tool_selection.py
"""

from __future__ import annotations

import clock
from db import embed_query, pg_query
from security import guardrails


def register(mcp) -> None:

    @mcp.tool(
        annotations={
            "title": "Search trouble tickets",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    )
    def search_tickets(
        status: str | None = None,
        severity: str | None = None,
        site_code: str | None = None,
        device_id: str | None = None,
        category: str | None = None,
        range: str = "last_30d",
        limit: int = 20,
    ) -> dict:
        """Search customer trouble tickets and engineer-raised incidents.

        Use this to answer questions about what has been REPORTED: open
        complaints, incident history, who raised what and when, and whether a
        device already has a case against it.

        Do NOT use this to find out what a device is actually doing right now -
        many faults never produce a ticket at all. For observed device behaviour
        use search_logs. For how a device is configured use get_device_config.

        CRITICAL WORKFLOW INSTRUCTION: When multiple tickets show simultaneous drop or failure symptoms across different edge devices, you MUST extract their device IDs and immediately call 'get_upstream_devices' with those IDs to find their common root cause (such as APE-NBI-03). Never stop at just listing the tickets.

        Args:
            status: open | in_progress | closed
            ... (โค้ดพารามิเตอร์เดิม) ...
        """
        start, end = clock.resolve_range(range)
        limit = guardrails.clamp_limit(limit, "search_tickets")

        conditions = ["opened_at BETWEEN %s AND %s"]
        params: list = [start, end]
        for column, value in (
            ("status", status), ("severity", severity), ("site_code", site_code),
            ("device_id", device_id), ("category", category),
        ):
            if value:
                conditions.append(f"{column} = %s")
                params.append(value)

        where = " AND ".join(conditions)
        total = pg_query(
            f"SELECT count(*) AS n FROM v_ticket_overview WHERE {where}", tuple(params)
        )[0]["n"]
        rows = pg_query(
            f"""SELECT ticket_id, category, severity, status, site_code, device_id,
                       device_role, circuit_id, customer_name, customer_segment,
                       service_type, title, opened_at, closed_at, assignee
                FROM v_ticket_overview
                WHERE {where}
                ORDER BY opened_at DESC
                LIMIT %s""",
            tuple(params + [limit]),
        )

        return guardrails.redact_deep({
            "total_matches": total,
            "returned": len(rows),
            "truncated": total > len(rows),
            "range": {"from": start.isoformat(), "to": end.isoformat()},
            "tickets": rows,
        })

    @mcp.tool(
        annotations={"title": "Get one ticket in full", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def get_ticket(ticket_id: str) -> dict:
        """Return one ticket with its full conversation history.

        Use after search_tickets when the summary is not enough - for example to
        read what the customer actually described, or what an engineer concluded
        before closing the case.

        Args:
            ticket_id: e.g. TK-25-00042
        """
        rows = pg_query(
            "SELECT * FROM v_ticket_overview WHERE ticket_id = %s", (ticket_id,)
        )
        if not rows:
            return {"found": False, "ticket_id": ticket_id,
                    "note": "ไม่พบ ticket หมายเลขนี้ในระบบ"}

        detail = pg_query(
            "SELECT description, resolution FROM tickets WHERE ticket_id = %s", (ticket_id,)
        )[0]
        messages = pg_query(
            """SELECT author, author_role, message, created_at
               FROM ticket_messages WHERE ticket_id = %s ORDER BY created_at""",
            (ticket_id,),
        )
        return guardrails.redact_deep(
            {"found": True, **rows[0], **detail, "messages": messages}
        )

    @mcp.tool(
        annotations={"title": "Search tickets by meaning", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def search_tickets_semantic(query: str, limit: int = 5) -> dict:
        """Find past tickets that describe a similar PROBLEM, worded differently.

        Use when looking for precedent: "has anything like this happened before,
        and what fixed it". Customers and engineers describe the same fault in
        very different words, which keyword search does not bridge.

        Do NOT use this for filtering by status, site or date - that is
        search_tickets, and it is both faster and exact.

        Args:
            query: a natural language description of the problem
            limit: how many similar tickets to return
        """
        limit = guardrails.clamp_limit(limit, "search_tickets_semantic", ceiling=20)
        vector = embed_query(query)

        if vector is None:
            # Degrade to trigram search rather than fail. The caller is told,
            # so the model can report reduced confidence instead of guessing.
            rows = pg_query(
                """SELECT ticket_id, title, status, severity, device_id,
                          similarity(title, %s) AS score
                   FROM tickets
                   WHERE similarity(title, %s) > 0.1
                   ORDER BY score DESC LIMIT %s""",
                (query, query, limit),
            )
            return guardrails.redact_deep({
                "method": "keyword_fallback",
                "warning": "embedding endpoint unavailable, results are keyword based",
                "results": rows,
            })

        rows = pg_query(
            """SELECT ticket_id, title, status, severity, category, device_id,
                      resolution, embedding <=> %s::vector AS distance
               FROM tickets
               WHERE embedding IS NOT NULL
               ORDER BY embedding <=> %s::vector
               LIMIT %s""",
            (str(vector), str(vector), limit),
        )
        if not rows:
            return {
                "method": "semantic",
                "results": [],
                "note": ("ยังไม่มี embedding ในตาราง tickets "
                         "ให้รัน make embed-tickets หรือทำ Lab 1 ให้เสร็จก่อน"),
            }
        return guardrails.redact_deep({"method": "semantic", "results": rows})

    @mcp.tool(
        annotations={"title": "Get device configuration", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def get_device_config(device_id: str) -> dict:
        """Return the stored configuration of one device, including per-interface MTU.

        Use when the question is about how a device is SET UP rather than how it
        is behaving: MTU, ISIS level and metric, interface descriptions.

        Configuration is where the cause of a fault usually lives; logs only show
        the symptom. When two devices will not form an adjacency, compare the
        configuration of BOTH ends - the mismatch is by definition not visible
        from one side.

        Args:
            device_id: e.g. PE-NBI-04
        """
        rows = pg_query(
            """SELECT d.device_id, d.site_code, d.role, d.vendor, d.model, d.os_version,
                      c.isis_level, c.isis_metric, c.default_mtu, c.snmp_location,
                      c.config_markdown, c.updated_at
               FROM devices d JOIN device_configs c ON c.device_id = d.device_id
               WHERE d.device_id = %s""",
            (device_id,),
        )
        if not rows:
            available = pg_query("SELECT device_id FROM devices ORDER BY device_id")
            return {
                "found": False,
                "device_id": device_id,
                "note": "ไม่พบอุปกรณ์นี้ในระบบ",
                "available_devices": [r["device_id"] for r in available],
            }

        interfaces = pg_query(
            """SELECT if_name, if_type, speed_mbps, mtu, admin_status, oper_status, description
               FROM interfaces WHERE device_id = %s ORDER BY if_name""",
            (device_id,),
        )
        return guardrails.redact_deep({"found": True, **rows[0], "interfaces": interfaces})

    @mcp.tool(
        annotations={"title": "List devices", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def list_devices(site_code: str | None = None, role: str | None = None) -> dict:
        """List every device the system knows about.

        Use this first when a question names a device that may not exist, or when
        you need to know the scope of the network before answering "which device
        is worst" style questions.

        Args:
            site_code: BKK or NBI. Omit for all sites.
            role: CR | PE | APE | LPE
        """
        conditions, params = [], []
        if site_code:
            conditions.append("site_code = %s")
            params.append(site_code)
        if role:
            conditions.append("role = %s")
            params.append(role)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = pg_query(
            f"""SELECT device_id, site_code, role, vendor, model, os_version, status
                FROM devices {where} ORDER BY role, device_id""",
            tuple(params),
        )
        return {"count": len(rows), "devices": rows,
                "sites_in_system": ["BKK", "NBI"]}

    @mcp.tool(
        annotations={"title": "Get circuits on a device", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def get_circuits_by_device(device_id: str) -> dict:
        """List customer circuits terminating on a device, grouped by segment.

        Use to quantify customer impact: how many customers are affected, who
        they are, and which service types are involved. This is the tool that
        turns "a device is down" into a statement a manager can act on.

        Args:
            device_id: e.g. APE-NBI-03
        """
        rows = pg_query(
            """SELECT c.circuit_id, c.service_type, c.bandwidth_mbps, c.status,
                      cu.customer_id, cu.name AS customer_name, cu.segment
               FROM circuits c JOIN customers cu ON cu.customer_id = c.customer_id
               WHERE c.device_id = %s
               ORDER BY cu.segment, cu.name""",
            (device_id,),
        )
        by_segment: dict[str, int] = {}
        for row in rows:
            by_segment[row["segment"]] = by_segment.get(row["segment"], 0) + 1
        return guardrails.redact_deep({
            "device_id": device_id,
            "circuit_count": len(rows),
            "customers_by_segment": by_segment,
            "circuits": rows,
        })
