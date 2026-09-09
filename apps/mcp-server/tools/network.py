"""Topology tools (Neo4j).

Neo4j answers relationship questions. The one that matters most in this
dataset is "what do these devices have in common upstream" - the question
that turns five unrelated-looking complaints into a single root cause.

No raw Cypher is ever accepted from the model. Every tool here runs a fixed,
parameterised query. Accepting generated Cypher would mean accepting whatever
a prompt injection can produce, and no keyword filter is reliable enough to
be the only defence.
"""

from __future__ import annotations
from contextvars import Context

import mcp

from db import embed_query, neo4j_query
from security import guardrails
from mcp.server.fastmcp import Context

def register(mcp) -> None:

    @mcp.tool(
        annotations={"title": "Get directly connected devices", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def get_device_neighbors(device_id: str) -> dict:
        """Return devices physically connected to this one, with adjacency state.

        Use for "what is this connected to" and as the first step when an
        adjacency is failing - the answer includes the peer you then need to
        compare configuration against.

        Note that a peer may be at a DIFFERENT site. Do not assume a fault is
        contained within one location.

        Args:
            device_id: e.g. PE-NBI-04
        """
        rows = neo4j_query(
            """MATCH (d:Device {device_id: $id})-[r:CONNECTED_TO]->(n:Device)
               OPTIONAL MATCH (d)-[isis:ISIS_NEIGHBOR]->(n)
               RETURN n.device_id AS neighbor, n.role AS role,
                      r.bandwidth_mbps AS bandwidth_mbps, r.status AS link_status,
                      isis.state AS isis_state, isis.level AS isis_level
               ORDER BY neighbor""",
            id=device_id,
        )
        if not rows:
            known = neo4j_query("MATCH (d:Device) RETURN d.device_id AS id ORDER BY id")
            return {"found": False, "device_id": device_id,
                    "note": "ไม่พบอุปกรณ์นี้ใน topology",
                    "available_devices": [r["id"] for r in known]}

        site = neo4j_query(
            "MATCH (d:Device {device_id:$id})-[:LOCATED_AT]->(s:Site) RETURN s.code AS site",
            id=device_id,
        )
        return {"found": True, "device_id": device_id,
                "site": site[0]["site"] if site else None,
                "neighbor_count": len(rows), "neighbors": rows}

    @mcp.tool(
        annotations={"title": "Find shared upstream devices", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def get_upstream_devices(device_ids: list[str] | str, max_hops: int = 4) -> dict | str:
        """Find the shared upstream router for a group of edge devices."""
        
        if isinstance(device_ids, str):
            device_ids = [d.strip() for d in device_ids.replace(",", " ").split() if d.strip()]

        if not device_ids:
            return {"error": "device_ids ต้องมีอย่างน้อย 1 ตัว"}

        try:
            rows = neo4j_query(
                """UNWIND $ids AS start_id
                    MATCH path = (d:Device {device_id: start_id})-[:UPLINK_TO*1..%d]->(up:Device)
                    RETURN start_id, up.device_id AS upstream, up.role AS role,
                           length(path) AS hops
                    ORDER BY start_id, hops""" % int(max_hops),
                ids=device_ids,
            )
        except Exception as e:
            # ปริ้นท์ error ออกมาดูใน console เวลาเทสต์
            print(f"\n[DEBUG ERROR in get_upstream_devices]: {e}\n")
            return f"Error querying network graph: {str(e)}"

        # Count how many of the inputs reach each upstream device.
        dependents: dict[str, set[str]] = {}
        roles: dict[str, str] = {}
        hop_of: dict[str, int] = {}
        for row in rows:
            up = row["upstream"]
            dependents.setdefault(up, set()).add(row["start_id"])
            roles[up] = row["role"]
            hop_of[up] = min(hop_of.get(up, 99), row["hops"])

        shared = [
            {
                "device_id": up,
                "role": roles[up],
                "hops": hop_of[up],
                "depends_on_it": sorted(sources),
                "dependent_count": len(sources),
            }
            for up, sources in dependents.items()
        ]
        # Closest common ancestor first: most dependants, then fewest hops.
        shared.sort(key=lambda x: (-x["dependent_count"], x["hops"]))

        common = [s for s in shared if s["dependent_count"] == len(set(device_ids))]
        
        # ป้องกันกรณีหา common ไม่เจอ เพื่อให้ AI อ่านง่ายขึ้น
        common_device = common[0]['device_id'] if common else "ไม่พบอุปกรณ์ที่เป็นจุดร่วม"

        return {
            "queried_devices": device_ids,
            "upstream_devices": shared,
            "shared_by_all": common,
            "interpretation": (
                f"อุปกรณ์ {common_device} เป็นจุดร่วมที่ใกล้ที่สุด "
                f"ของอุปกรณ์ทั้ง {len(set(device_ids))} ตัวที่ถามมา"
                if common else
                "ไม่พบอุปกรณ์ upstream ที่เป็นจุดร่วมของทุกตัวที่ถามมา"
            ),
        }

    @mcp.tool(
        annotations={"title": "Find shared upstream devices", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def get_upstream_devices(device_ids: list[str] | str, max_hops: int = 4) -> dict | str:
        """Find the shared upstream router for a group of edge devices."""
        
        if isinstance(device_ids, str):
            device_ids = [d.strip() for d in device_ids.replace(",", " ").split() if d.strip()]

        if not device_ids:
            return {"error": "device_ids ต้องมีอย่างน้อย 1 ตัว"}

        try:
            rows = neo4j_query(
                """UNWIND $ids AS start_id
                    MATCH path = (d:Device {device_id: start_id})-[:UPLINK_TO*1..%d]->(up:Device)
                    RETURN start_id, up.device_id AS upstream, up.role AS role,
                           length(path) AS hops
                    ORDER BY start_id, hops""" % int(max_hops),
                ids=device_ids,
            )
        except Exception as e:
            # ปริ้นท์ error ออกมาดูใน console เวลาเทสต์
            print(f"\n[DEBUG ERROR in get_upstream_devices]: {e}\n")
            return f"Error querying network graph: {str(e)}"

        # --- ส่วนที่เพิ่มเติมเข้ามาเพื่อประมวลผลข้อมูลหาตัวที่เชื่อมร่วมกัน (Shared Upstream) ---
        # เก็บว่า upstream แต่ละตัว มี device ตัวไหนเชื่อมมาบ้าง
        upstream_map = {}
        for row in rows:
            up_id = row.get("upstream")
            start_id = row.get("start_id")
            role = row.get("role")
            if not up_id:
                continue
            if up_id not in upstream_map:
                upstream_map[up_id] = {"role": role, "connected_devices": set()}
            upstream_map[up_id]["connected_devices"].add(start_id)

        # หาตัวที่เชื่อมครบทุก device_id ที่ส่งมาทั้งหมด
        total_queried = len(set(device_ids))
        shared_all = []
        for up_id, data in upstream_map.items():
            if len(data["connected_devices"]) >= total_queried:
                shared_all.append({
                    "device_id": up_id,
                    "role": data["role"],
                    "dependent_count": len(data["connected_devices"])
                })

        return {
            "queried_devices": device_ids,
            "upstream_paths": rows,
            "shared_by_all": shared_all
        }

    @mcp.tool(
        annotations={"title": "Find path between devices", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def get_path_between(from_device: str, to_device: str) -> dict:
        """Return the shortest topology path between two devices.

        Use to answer "how does traffic get from here to there" and to identify
        every device that a flow depends on.

        Args:
            from_device: e.g. LPE-NBI-11
            to_device: e.g. CR-BKK-01
        """
        rows = neo4j_query(
            """MATCH (a:Device {device_id:$a}), (b:Device {device_id:$b})
               MATCH path = shortestPath((a)-[:CONNECTED_TO*..8]-(b))
               RETURN [n IN nodes(path) | n.device_id] AS hops,
                      length(path) AS hop_count""",
            a=from_device, b=to_device,
        )
        if not rows:
            return {"found": False,
                    "note": f"ไม่พบเส้นทางระหว่าง {from_device} กับ {to_device}"}
        return {"found": True, "from": from_device, "to": to_device, **rows[0]}

    @mcp.tool(
        annotations={"title": "Get site topology", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def get_site_topology(site_code: str) -> dict:
        """Return every device at a site and how they connect to each other.

        Args:
            site_code: BKK or NBI
        """
        devices = neo4j_query(
            """MATCH (d:Device)-[:LOCATED_AT]->(s:Site {code:$code})
               RETURN d.device_id AS device_id, d.role AS role ORDER BY d.role, device_id""",
            code=site_code,
        )
        if not devices:
            return {"found": False, "site_code": site_code,
                    "note": "ไม่พบพื้นที่นี้ในระบบ ระบบครอบคลุมเฉพาะ BKK และ NBI",
                    "available_sites": ["BKK", "NBI"]}
        links = neo4j_query(
            """MATCH (a:Device)-[:LOCATED_AT]->(s:Site {code:$code})
               MATCH (a)-[r:UPLINK_TO]->(b:Device)
               RETURN a.device_id AS from_device, b.device_id AS to_device,
                      r.bandwidth_mbps AS bandwidth_mbps""",
            code=site_code,
        )
        return {"found": True, "site_code": site_code,
                "device_count": len(devices), "devices": devices, "links": links}

    @mcp.tool(
        annotations={"title": "Find devices by description", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def search_devices_semantic(query: str, limit: int = 5) -> dict:
        """Find devices by describing their ROLE in words rather than naming them.

        Example: "the routers that collect traffic from local access equipment".
        Useful when the user does not know the naming convention.

        Do NOT use this when the device name is already known - use
        get_device_config or get_device_neighbors directly, they are exact.

        Args:
            query: a description of the kind of device you are looking for
            limit: how many devices to return
        """
        limit = guardrails.clamp_limit(limit, "search_devices_semantic", ceiling=10)
        vector = embed_query(query)
        if vector is None:
            rows = neo4j_query(
                """CALL db.index.fulltext.queryNodes('device_fulltext', $q)
                   YIELD node, score
                   RETURN node.device_id AS device_id, node.profile_text AS profile,
                          score LIMIT $limit""",
                q=query, limit=limit,
            )
            return {"method": "fulltext_fallback",
                    "warning": "embedding endpoint unavailable", "results": rows}

        rows = neo4j_query(
            """CALL db.index.vector.queryNodes('device_embedding', $limit, $vec)
               YIELD node, score
               RETURN node.device_id AS device_id, node.role AS role,
                      node.profile_text AS profile, score
               ORDER BY score DESC""",
            limit=limit, vec=vector,
        )
        return {"method": "vector", "results": rows}
