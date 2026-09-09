# แก้ปัญหาที่พบบ่อย

---

## 1. ติดตั้งและเปิดระบบ

| อาการ | สาเหตุ | วิธีแก้ |
|---|---|---|
| OpenSearch restart วนไม่จบ | RAM ที่ให้ Docker น้อยเกินไป | Docker Desktop → Settings → Resources → Memory ≥ **8 GB** |
| `make up` ค้างที่ seeder | Neo4j ยังบูตไม่เสร็จ (ใช้เวลานานกว่าตัวอื่น) | รอ 60 วินาที ถ้ายังค้างให้ `make down && make up` |
| Port ชนกัน | มีบริการอื่นใช้ port อยู่ | `lsof -i :5432` แล้วปิด หรือแก้ port ใน `docker/docker-compose.yml` |
| `make verify` FAIL ทุกข้อ | seed ยังไม่ทำงาน | `make seed` แล้วดู log |
| pgAdmin ล็อกอินไม่ได้ | ค่าใน `.env` ไม่ตรง | ค่าเริ่มต้น `workshop@example.local` / `workshop` |

---

## 2. LLM และ Embedding

| อาการ | สาเหตุ | วิธีแก้ |
|---|---|---|
| `Connection refused` ไปที่ LLM | ยังไม่ได้ต่อ VPN หรือ URL ผิด | `curl $LLM_BASE_URL/models` ทดสอบก่อน · URL **ต้องลงท้ายด้วย `/v1`** |
| ตอบช้ามาก | หลายคนใช้ GPU ตัวเดียวกัน | ระหว่าง lab ใช้ `LLM_MODEL=$LLM_MODEL_FAST` |
| `[WARN] ticket embeddings empty` | embedding endpoint ต่อไม่ได้ตอน seed | `make embed-tickets && make embed-devices` |
| JSON ที่ได้ไม่ผ่าน schema บ่อย | gateway ไม่รองรับ guided decoding | ตั้ง `LLM_GUIDED_DECODING=false` แล้วพึ่ง auto-retry |
| `usage` ไม่มีใน stream | gateway ไม่รองรับ `stream_options` | นับเองด้วย `agent/tokenizer.py` |
| มิติ embedding ไม่ตรง | โมเดลคนละตัวกับที่ตั้งไว้ | ตรวจ `EMBEDDING_DIM` ให้ตรงกับ column และ mapping ทั้งสามที่ |

---

## 3. MCP Server

| อาการ | สาเหตุ | วิธีแก้ |
|---|---|---|
| **Claude Desktop ไม่เห็น server** | ใช้ relative path ใน config | ต้องเป็น **absolute path** เท่านั้น |
| **server ขึ้นแล้ว error ทันที** | มี `print()` ลง stdout | stdout เป็นของโปรโตคอล ให้ log ลง **stderr** |
| tool ทำงานแต่ข้อมูลว่าง | container ยังไม่ได้เปิด | `docker ps` ตรวจว่าครบ |
| `ModuleNotFoundError` เมื่อรันผ่าน client | ไม่ได้อยู่ใน environment เดียวกัน | ใช้ `uv --directory <abs> run python ...` |
| tool ถูกปฏิเสธทั้งที่ไม่ควร | keyword filter จับคำในข้อมูล | ตรวจ `_WRITE_KEYWORDS` — ต้อง match เป็นคำเต็ม |

---

## 4. Agent

| อาการ | สาเหตุ | วิธีแก้ |
|---|---|---|
| Plan อ้าง tool ที่ไม่มี | ไม่ได้ validate | `validate_plan()` ต้องตัดออกก่อนรัน |
| Agent วนไม่จบ | Loop Guard ไม่ทำงาน | ตรวจว่าเรียก `guard.check()` **ก่อน**ทุกครั้งที่เรียก tool |
| ตอบว่าไม่รู้ทั้งที่มีข้อมูล | ผลลัพธ์ถูกตัดจนหมด | เพิ่ม `MCP_MAX_ROWS` หรือใช้ `count_log_events` แทน |
| context โตไม่หยุด | ไม่ตรวจการเปลี่ยนเรื่อง | ดู [day2/lab3](../day2/lab3-context-memory.md) |
| **คำถามนอกขอบเขตล้าง context** | ตรวจ topic shift ก่อน intent | สลับลำดับ — **intent ต้องมาก่อนเสมอ** |
| อ้างวันที่ผิด | โมเดลเดาวันที่เอง | ให้อ่าน `clock://now` ก่อนวางแผน · รับเฉพาะช่วงเวลาสัมพัทธ์ |

---

## 5. UI

| อาการ | สาเหตุ | วิธีแก้ |
|---|---|---|
| **stream ค้าง ไม่มีอะไรขึ้น** | ลืมบรรทัดว่างท้าย SSE | ต้องลงท้ายด้วย `\n\n` |
| event หายบางส่วน | parse ทีละ chunk | ต้อง buffer แล้วแยกที่ `\n\n` เอง |
| Step ไม่ปิด | ไม่ได้เรียก `__aexit__` | ต้องเรียกทุกครั้ง แม้ตอน error |
| ภาษาไทยเพี้ยนใน CSV | Excel ไม่อ่าน UTF-8 | เขียนด้วย `utf-8-sig` |

---

## 6. ข้อมูล

| อาการ | สาเหตุ | วิธีแก้ |
|---|---|---|
| **ถาม "24 ชั่วโมงที่ผ่านมา" แล้วไม่เจออะไร** | seed ไว้นานแล้ว | `make reseed` — ทำทุกเช้าวันเดโม |
| ข้อมูลไม่ตรงกับ scenario | แก้ scenario แต่ไม่ได้ seed ใหม่ | `make reseed && make verify` |
| ผลลัพธ์ต่างกันทุกครั้งที่รัน test | ไม่ได้ตรึงเวลา | ตั้ง `DEMO_NOW` และ `SEED_RANDOM_SEED=42` |

---

## 7. คำสั่งช่วยวินิจฉัย

```bash
docker compose -f docker/docker-compose.yml ps
```

```bash
docker compose -f docker/docker-compose.yml logs --tail 50 opensearch
```

```bash
curl -s localhost:9200/_cluster/health | python3 -m json.tool
```

```bash
make verify
```

---

## 8. เริ่มใหม่ทั้งหมด

```bash
make reset && make up && make verify
```
