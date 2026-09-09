# Neo4j seed

| ไฟล์ | เนื้อหา |
|---|---|
| `01_topology.cypher` | Site, Device, Interface, ลิงก์, ISIS/CDP adjacency (สร้างโดย seeder) |
| Customer / Circuit | สร้างโดย `docker/seeder/seed.py` เพราะต้องให้ตรงกับ PostgreSQL |

## ตรวจผลด้วยตาที่ Neo4j Browser

เปิด http://localhost:7474 แล้วลอง:

```cypher
MATCH (d:Device)-[:LOCATED_AT]->(s:Site) RETURN d, s
```

ดูโครงสร้างที่เป็นหัวใจของ scenario S1:

```cypher
MATCH p = (l:Device {role:'LPE'})-[:UPLINK_TO]->(a:Device) RETURN p
```

ดู adjacency ที่ล่ม (scenario S3):

```cypher
MATCH (a)-[r:ISIS_NEIGHBOR {state:'Down'}]->(b) RETURN a, r, b
```
