# Cheat Sheet

---

## SQL (PostgreSQL)

```sql
-- อุปกรณ์ทั้งหมด
SELECT device_id, site_code, role, model FROM devices ORDER BY site_code, role;

-- ticket ที่ยังไม่ปิด เรียงตามความรุนแรง
SELECT ticket_id, severity, device_id, title, opened_at
FROM tickets WHERE status <> 'closed'
ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                       WHEN 'medium' THEN 3 ELSE 4 END, opened_at DESC;

-- MTU ทุก interface (scenario S3 อยู่ตรงนี้)
SELECT device_id, if_name, mtu, description FROM interfaces ORDER BY device_id;

-- อุปกรณ์ที่ไม่มี ticket เลย (scenario S2)
SELECT d.device_id FROM devices d
LEFT JOIN tickets t ON t.device_id = d.device_id
WHERE t.ticket_id IS NULL;

-- ลูกค้าที่จะกระทบถ้าปิดอุปกรณ์
SELECT cu.segment, count(*) FROM circuits c
JOIN customers cu ON cu.customer_id = c.customer_id
WHERE c.device_id = 'APE-NBI-03' GROUP BY cu.segment;
```

### pgvector

```sql
ALTER TABLE tickets ADD COLUMN embedding vector(768);

CREATE INDEX idx_tickets_embedding ON tickets
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- <=> cosine distance (ยิ่งน้อยยิ่งใกล้) · <-> L2 · <#> inner product
SELECT ticket_id, title, embedding <=> :q AS d
FROM tickets ORDER BY embedding <=> :q LIMIT 5;

SELECT count(*), count(embedding) FROM tickets;
```

---

## Cypher (Neo4j)

```cypher
// อุปกรณ์ทั้งหมดพร้อมพื้นที่
MATCH (d:Device)-[:LOCATED_AT]->(s:Site) RETURN d.device_id, d.role, s.code;

// เพื่อนบ้านโดยตรง
MATCH (d:Device {device_id:'APE-NBI-03'})-[r:CONNECTED_TO]->(n)
RETURN n.device_id, r.bandwidth_mbps;

// หา upstream ร่วม  <- หัวใจของ scenario S1
MATCH (d:Device)-[:UPLINK_TO*1..4]->(up:Device)
WHERE d.device_id IN ['LPE-NBI-11','LPE-NBI-12','LPE-NBI-13']
RETURN up.device_id, count(DISTINCT d) AS dependents
ORDER BY dependents DESC;

// อะไรอยู่ใต้อุปกรณ์นี้
MATCH (down:Device)-[:UPLINK_TO*1..4]->(:Device {device_id:'APE-NBI-03'})
RETURN down.device_id;

// adjacency ที่ล่ม  <- scenario S3
MATCH (a)-[r:ISIS_NEIGHBOR {state:'Down'}]->(b)
RETURN a.device_id, b.device_id;

// เส้นทางสั้นสุด
MATCH p = shortestPath((:Device {device_id:'LPE-NBI-11'})
                       -[:CONNECTED_TO*..8]-(:Device {device_id:'CR-BKK-01'}))
RETURN [n IN nodes(p) | n.device_id];
```

### Vector index

```cypher
CREATE VECTOR INDEX device_embedding IF NOT EXISTS
FOR (d:Device) ON (d.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: 768,
                         `vector.similarity_function`: 'cosine' }};

CALL db.index.vector.queryNodes('device_embedding', 5, $vec)
YIELD node, score RETURN node.device_id, score;
```

---

## OpenSearch DSL

```bash
# นับทั้งหมด
curl -s 'localhost:9200/network-logs-*/_count'
```

```json
// ค้น log ของอุปกรณ์ในช่วงเวลา
GET network-logs-*/_search
{"size":20,"sort":[{"@timestamp":"desc"}],
 "query":{"bool":{"must":[
   {"term":{"device_id":"APE-NBI-03"}},
   {"range":{"@timestamp":{"gte":"now-14d"}}}]}}}
```

```json
// นับตามอุปกรณ์ + ดูแนวโน้ม
GET network-logs-*/_search
{"size":0,
 "aggs":{"by_device":{"terms":{"field":"device_id","size":20},
   "aggs":{"over_time":{"date_histogram":{"field":"@timestamp","fixed_interval":"1d"}}}}}}
```

```json
// vector search
GET network-docs/_search
{"size":5,"query":{"knn":{"embedding":{"vector":[...],"k":5}}}}
```

```json
// บรรทัดที่ parse ไม่ได้
GET network-logs-*/_search
{"query":{"term":{"parse_status":"failed"}}}
```

---

## MCP

```bash
make protocol-version
```

```bash
npx @modelcontextprotocol/inspector python apps/mcp-server/server.py
```

```bash
curl -s -X POST http://localhost:9000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

| method | ทำอะไร |
|---|---|
| `initialize` | เริ่มต้น แลก capabilities |
| `tools/list` · `tools/call` | รายการ tool · เรียก tool |
| `resources/list` · `resources/read` | รายการ resource · อ่าน |
| `prompts/list` · `prompts/get` | รายการ prompt · ดึงเทมเพลต |
| `elicitation/create` | server ขอข้อมูลจากผู้ใช้ |

---

## Make

| คำสั่ง | ทำอะไร |
|---|---|
| `make up` / `make down` / `make reset` | เปิด / ปิด / ล้างทั้งหมด |
| `make verify` | ตรวจข้อมูลครบทั้ง 3 ฐาน |
| `make reseed` | สร้างข้อมูลใหม่ให้ timestamp สดใหม่ |
| `make load-logs [FILE=... SHIFT=now]` | โหลด log เข้า OpenSearch |
| `make api` / `make ui` / `make mcp` | รัน Agent API / Chainlit / MCP Server |
| `make demo` / `make demo-offline` | เปิดแอปสำเร็จรูป |
| `make lab1-reset` | ลบ vector เพื่อทำ Lab 1 |
| `make embed-tickets` / `make embed-devices` | เติม vector |
| `make vector-compare` | เทียบ vector store 3 ตัว |
| `make test` / `make eval` | ตรวจงาน / วัดคุณภาพ |

---

## ชื่ออุปกรณ์ในระบบ

| BKK | NBI |
|---|---|
| `CR-BKK-01` Core หลัก | `PE-NBI-01` PE |
| `CR-BKK-02` Core สำรอง | `PE-NBI-04` **S3 MTU 1500** |
| `PE-BKK-02` **S2 เสื่อมเงียบ** | `APE-NBI-03` **S1 flapping** |
| `APE-BKK-05` **S4 maintenance** | `LPE-NBI-11/12/13` |
