"""Log and document tools (OpenSearch).

Two very different kinds of retrieval live here:

  search_logs / count_log_events  - structured filtering over device syslog.
      No vectors. Filtering by device and time answers these questions exactly,
      and embedding two thousand log lines would cost more and answer worse.

  search_docs_semantic            - vector search over runbooks and configs.
      This is where meaning matters, because the words an engineer writes in a
      runbook are not the words a customer uses in a ticket.

Knowing which of the two a question needs is the skill this module teaches.
"""

from __future__ import annotations

import clock
from config import settings
from db import embed_query, opensearch
from security import guardrails


def _index() -> str:
    return f"{settings().log_index}-*"


def register(mcp) -> None:

    @mcp.tool(
        annotations={"title": "Search device logs", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def search_logs(
        device_id: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        contains: str | None = None,
        range: str = "last_24h",
        limit: int = 30,
    ) -> dict | str: # <--- อัปเดต Type Hint ตรงนี้ให้คืนค่าเป็น str ได้ด้วย
        """Search device logs and system events over a specific time range. Use this to investigate historical issues, find error messages, or check interface status changes. Requires a relative time range like 'last_24h' or 'last_7d'."""
        
        try:
            # ของเดิมจะมีบรรทัดคล้ายๆ แบบนี้อยู่
            start, end = clock.resolve_range(range) 
        except ValueError as e:
            # เพิ่มบล็อกนี้เข้าไป เพื่อคืนค่า Error กลับไปเป็นข้อความให้ AI รู้ตัว
            return f"Error: {e}"

        # ... (โค้ดเดิมที่เหลือสำหรับดึง Log ปล่อยไว้เหมือนเดิม) ...
        # ...
        """Search raw device logs - what the equipment actually reported.

        Use for observed behaviour: interfaces changing state, adjacencies
        dropping, CRC errors, CPU warnings, reloads.

        Important: a burst of severe log entries is NOT automatically an
        incident. Planned maintenance produces logs that look identical to a
        major outage. Before describing anything as a fault, check
        search_tickets with category "maintenance" for the same window.

        Args:
            device_id: e.g. APE-NBI-03
            severity: critical | error | warning | notice | info
            event_type: e.g. LINK-UPDOWN, ISIS-ADJCHANGE, LINEPROTO-CRC
            contains: free text to match inside the message
            range: last_1h, last_6h, last_24h, last_3d, last_7d, last_14d, last_30d
            limit: maximum log lines to return
        """
        start, end = clock.resolve_range(range)
        limit = guardrails.clamp_limit(limit, "search_logs",
                                       ceiling=settings().max_log_results)

        must: list[dict] = [
            {"range": {"@timestamp": {"gte": start.isoformat(), "lte": end.isoformat()}}}
        ]
        for field, value in (("device_id", device_id), ("severity", severity),
                             ("event_type", event_type)):
            if value:
                must.append({"term": {field: value}})
        if contains:
            must.append({"match": {"message": contains}})

        body = {
            "size": limit,
            "query": {"bool": {"must": must}},
            "sort": [{"@timestamp": "desc"}],
            "track_total_hits": True,
        }
        response = opensearch().search(index=_index(), body=body)
        total = response["hits"]["total"]["value"]
        hits = [h["_source"] for h in response["hits"]["hits"]]

        return guardrails.redact_deep({
            "total_matches": total,
            "returned": len(hits),
            "truncated": total > len(hits),
            "range": {"from": start.isoformat(), "to": end.isoformat()},
            "logs": [
                {k: v for k, v in hit.items()
                 if k in ("@timestamp", "device_id", "severity", "event_type",
                          "interface", "message")}
                for hit in hits
            ],
            "note": ("ผลลัพธ์ถูกตัดจำนวน ใช้ count_log_events เพื่อดูภาพรวมแทนการดึงทั้งหมด"
                     if total > len(hits) else None),
        })

    @mcp.tool(
        annotations={"title": "Aggregate log events", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def count_log_events(
        group_by: str = "device_id",
        severity: str | None = None,
        range: str = "last_7d",
        interval: str | None = None,
    ) -> dict:
        """Count log events grouped by device, event type or severity.

        Use instead of search_logs whenever the question is "how many", "which
        one has the most", or "is this getting worse". Aggregating server-side
        returns a small answer where fetching raw lines would overflow the
        context window and still not answer the question.

        Set `interval` to also get a time series, which is how you tell a device
        that is steadily degrading from one that had a single bad day. A rising
        trend matters more than a large total.

        Args:
            group_by: device_id | event_type | severity | site_code
            severity: restrict to one severity level
            range: last_24h, last_7d, last_14d, last_30d
            interval: optional bucket size for a trend, e.g. 1d or 6h
        """
        start, end = clock.resolve_range(range)
        allowed = {"device_id", "event_type", "severity", "site_code", "device_role"}
        if group_by not in allowed:
            return {"error": f"group_by ต้องเป็นหนึ่งใน {sorted(allowed)}"}

        must: list[dict] = [
            {"range": {"@timestamp": {"gte": start.isoformat(), "lte": end.isoformat()}}}
        ]
        if severity:
            must.append({"term": {"severity": severity}})

        aggs: dict = {"grouped": {"terms": {"field": group_by, "size": 20}}}
        if interval:
            aggs["grouped"]["aggs"] = {
                "over_time": {
                    "date_histogram": {"field": "@timestamp", "fixed_interval": interval}
                }
            }

        response = opensearch().search(
            index=_index(),
            body={"size": 0, "query": {"bool": {"must": must}}, "aggs": aggs},
        )

        results = []
        for bucket in response["aggregations"]["grouped"]["buckets"]:
            entry = {"key": bucket["key"], "count": bucket["doc_count"]}
            if interval and "over_time" in bucket:
                series = [
                    {"at": b["key_as_string"], "count": b["doc_count"]}
                    for b in bucket["over_time"]["buckets"]
                ]
                entry["series"] = series
                # A simple first-half vs second-half comparison is enough to
                # separate "steady" from "getting worse", and it is explainable.
                half = len(series) // 2
                if half:
                    early = sum(b["count"] for b in series[:half])
                    late = sum(b["count"] for b in series[half:])
                    entry["trend"] = (
                        "increasing" if late > early * 1.5
                        else "decreasing" if early > late * 1.5
                        else "steady"
                    )
            results.append(entry)

        return {
            "group_by": group_by,
            "range": {"from": start.isoformat(), "to": end.isoformat()},
            "total_events": response["hits"]["total"]["value"],
            "results": results,
        }

    @mcp.tool(
        annotations={"title": "Search runbooks and configs by meaning",
                     "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
    )
    def search_docs_semantic(query: str, limit: int = 5,
                             source_type: str | None = None) -> dict:
        """Search operational documentation by meaning: runbooks and device configs.

        Use for "how do we normally handle this", "has this been documented",
        and for procedure lookups. The documents are written by engineers, so
        ask in terms of the technical symptom rather than the customer wording.

        Do NOT use this to find out what happened - that is search_logs. This
        tool returns knowledge, not events.

        Args:
            query: natural language description of the problem or procedure
            limit: how many chunks to return
            source_type: runbook | config
        """
        limit = guardrails.clamp_limit(limit, "search_docs_semantic", ceiling=20)
        index = settings().doc_index
        vector = embed_query(query)

        filters = [{"term": {"source_type": source_type}}] if source_type else []

        if vector is None:
            body = {
                "size": limit,
                "query": {"bool": {"must": [{"match": {"content": query}}],
                                   "filter": filters}},
            }
            response = opensearch().search(index=index, body=body)
            return guardrails.redact_deep({
                "method": "keyword_fallback",
                "warning": "embedding endpoint unavailable, results are keyword based",
                "results": [
                    {"title": h["_source"]["title"], "content": h["_source"]["content"],
                     "score": h["_score"]}
                    for h in response["hits"]["hits"]
                ],
            })

        knn: dict = {"embedding": {"vector": vector, "k": limit}}
        if filters:
            knn["embedding"]["filter"] = {"bool": {"filter": filters}}
        response = opensearch().search(
            index=index, body={"size": limit, "query": {"knn": knn}}
        )
        hits = response["hits"]["hits"]
        if not hits:
            return {"method": "vector", "results": [],
                    "note": "ยังไม่มี embedding ใน network-docs ให้รัน make reseed"}

        return guardrails.redact_deep({
            "method": "vector",
            "results": [
                {
                    "title": h["_source"]["title"],
                    "source_type": h["_source"].get("source_type"),
                    "device_id": h["_source"].get("device_id"),
                    "content": h["_source"]["content"],
                    "score": h["_score"],
                }
                for h in hits
            ],
        })

    @mcp.tool(
        annotations={"title": "Calculate equipment health score", "readOnlyHint": True,
                     "idempotentHint": True, "openWorldHint": False}
    )
    def calculate_health_score(device_id: str | None = None,
                               range: str = "last_30d") -> dict:
        """Score device health from log behaviour, weighted toward recent trend.

        Use to find equipment that is degrading BEFORE anyone raises a ticket.
        The absence of tickets is not evidence of health: a device can decline
        for weeks without any customer noticing.

        Scoring gives more weight to a rising error rate than to a large total,
        because a device that had one bad day last month is in better shape than
        one whose error count doubles every week.

        Args:
            device_id: score one device. Omit to score every device and rank them.
            range: window to analyse
        """
        start, end = clock.resolve_range(range)
        must: list[dict] = [
            {"range": {"@timestamp": {"gte": start.isoformat(), "lte": end.isoformat()}}}
        ]
        if device_id:
            must.append({"term": {"device_id": device_id}})

        response = opensearch().search(
            index=_index(),
            body={
                "size": 0,
                "query": {"bool": {"must": must}},
                "aggs": {
                    "by_device": {
                        "terms": {"field": "device_id", "size": 50},
                        "aggs": {
                            "by_severity": {"terms": {"field": "severity", "size": 10}},
                            "over_time": {
                                "date_histogram": {"field": "@timestamp",
                                                   "fixed_interval": "1d"}
                            },
                        },
                    }
                },
            },
        )

        scored = []
        for bucket in response["aggregations"]["by_device"]["buckets"]:
            severities = {b["key"]: b["doc_count"] for b in bucket["by_severity"]["buckets"]}
            critical = severities.get("critical", 0)
            errors = severities.get("error", 0)
            warnings = severities.get("warning", 0)

            series = [b["doc_count"] for b in bucket["over_time"]["buckets"]]
            half = len(series) // 2
            early = sum(series[:half]) or 1
            late = sum(series[half:])
            trend_ratio = late / early

            # 100 is healthy. Volume costs points; an upward trend costs more.
            score = 100.0
            score -= min(critical * 3.0, 25)
            score -= min(errors * 0.5, 25)
            score -= min(warnings * 0.15, 20)
            if trend_ratio > 1.5:
                score -= min((trend_ratio - 1) * 18, 30)

            scored.append({
                "device_id": bucket["key"],
                "health_score": round(max(score, 0), 1),
                "grade": ("good" if score >= 80 else
                          "watch" if score >= 60 else
                          "at_risk" if score >= 40 else "critical"),
                "critical_events": critical,
                "error_events": errors,
                "warning_events": warnings,
                "trend_ratio": round(trend_ratio, 2),
                "trend": ("worsening" if trend_ratio > 1.5 else
                          "improving" if trend_ratio < 0.67 else "steady"),
            })

        scored.sort(key=lambda d: d["health_score"])
        return {
            "range": {"from": start.isoformat(), "to": end.isoformat()},
            "scoring_note": (
                "คะแนนเต็ม 100 หักตามปริมาณ event และหักเพิ่มถ้าแนวโน้มเพิ่มขึ้น "
                "อุปกรณ์ที่ไม่มี ticket อาจมีคะแนนต่ำได้ ถ้ากำลังเสื่อมลงเงียบๆ"
            ),
            "devices": scored,
            "worst": scored[0] if scored else None,
        }
