"""Expose database structure as MCP Resources.

The difference between Tools and Resources in one sentence: a Tool is
something the model calls to make something happen; a Resource is something
the model reads to understand the world before it acts.

Schema belongs in Resources. A model that has read the schema stops guessing
column names, stops inventing tables, and produces plans whose steps are
actually executable.
"""

from __future__ import annotations

import json

from config import settings
from db import neo4j_query, opensearch, pg_query


def register(mcp) -> None:

    @mcp.resource("schema://postgres")
    def postgres_schema() -> str:
        """Tables, columns and comments in the ticket and configuration database."""
        tables = pg_query(
            """SELECT c.table_name, c.column_name, c.data_type, c.is_nullable,
                      col_description(pgc.oid, c.ordinal_position) AS comment
               FROM information_schema.columns c
               JOIN pg_class pgc ON pgc.relname = c.table_name
               WHERE c.table_schema = 'public'
               ORDER BY c.table_name, c.ordinal_position"""
        )
        grouped: dict[str, list] = {}
        for row in tables:
            grouped.setdefault(row["table_name"], []).append(
                {
                    "column": row["column_name"],
                    "type": row["data_type"],
                    "nullable": row["is_nullable"] == "YES",
                    "comment": row["comment"],
                }
            )
        counts = {
            name: pg_query(f"SELECT count(*) AS n FROM {name}")[0]["n"]
            for name in grouped
            if not name.startswith("v_")
        }
        return json.dumps(
            {
                "database": "PostgreSQL",
                "purpose": "Trouble tickets, device configuration, circuits and customers",
                "tables": grouped,
                "row_counts": counts,
                "guidance": (
                    "Prefer the view v_ticket_overview over joining tickets, circuits "
                    "and customers by hand. Access is read-only."
                ),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    @mcp.resource("schema://neo4j")
    def neo4j_schema() -> str:
        """Node labels, relationship types and their meanings in the topology graph."""
        labels = neo4j_query(
            "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label"
        )
        relationships = neo4j_query(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY type"
        )
        return json.dumps(
            {
                "database": "Neo4j",
                "purpose": "Physical topology and adjacency relationships",
                "node_labels": labels,
                "relationship_types": relationships,
                "semantics": {
                    "UPLINK_TO": "Points from a subordinate device toward its aggregation "
                                 "point. Following it upward finds shared dependencies.",
                    "CONNECTED_TO": "Bidirectional physical link.",
                    "ISIS_NEIGHBOR": "Routing adjacency. The `state` property is Up or Down.",
                    "CDP_NEIGHBOR": "Discovery protocol neighbour, collected separately.",
                    "SERVED_BY": "Circuit terminates on a device.",
                    "OWNS": "Customer owns a circuit.",
                    "LOCATED_AT": "Device is installed at a site.",
                },
                "guidance": (
                    "Adjacencies can cross sites. Never restrict a topology search to "
                    "one site when diagnosing an adjacency problem."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    @mcp.resource("schema://opensearch")
    def opensearch_schema() -> str:
        """Index mappings and what each index is for."""
        client = opensearch()
        result: dict = {"database": "OpenSearch", "indices": {}}
        for pattern, purpose in (
            (f"{settings().log_index}-*",
             "Raw device syslog. Filter by device and time; no vector search here."),
            (settings().doc_index,
             "Runbooks and configs, chunked and embedded. Vector search lives here."),
        ):
            try:
                mappings = client.indices.get_mapping(index=pattern)
                for index_name, mapping in mappings.items():
                    result["indices"][index_name] = {
                        "purpose": purpose,
                        "fields": sorted(mapping["mappings"].get("properties", {})),
                        "doc_count": client.count(index=index_name)["count"],
                    }
            except Exception as exc:  # noqa: BLE001
                result["indices"][pattern] = {"error": str(exc)}
        result["guidance"] = (
            "Log questions are filter questions: use count_log_events for "
            "'how many' and search_logs for 'show me'. Use search_docs_semantic "
            "only for documentation, never for events."
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.resource("schema://overview")
    def overview() -> str:
        """Which database answers which kind of question. Read this first."""
        return json.dumps(
            {
                "system": "NT IP-MPLS network operations assistant",
                "scope": {
                    "sites": ["BKK", "NBI"],
                    "device_count": 10,
                    "device_roles": {
                        "CR": "Core Router",
                        "PE": "Provider Edge",
                        "APE": "Aggregation PE",
                        "LPE": "Local PE, customers connect here",
                    },
                },
                "routing_questions_to_stores": {
                    "what was reported": "PostgreSQL via search_tickets",
                    "how is it configured": "PostgreSQL via get_device_config",
                    "what connects to what": "Neo4j via get_device_neighbors",
                    "what do these have in common": "Neo4j via get_upstream_devices",
                    "what did the equipment report": "OpenSearch via search_logs",
                    "how many / which is worst": "OpenSearch via count_log_events",
                    "how do we normally fix this": "OpenSearch via search_docs_semantic",
                },
                "hard_rules": [
                    "Anything outside BKK and NBI does not exist here. Say so.",
                    "A device not returned by list_devices does not exist. Do not invent one.",
                    "Severe logs during a maintenance window are not an incident. "
                    "Check tickets with category 'maintenance' first.",
                    "There is no real-time telemetry. Only logs, tickets and configuration.",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
