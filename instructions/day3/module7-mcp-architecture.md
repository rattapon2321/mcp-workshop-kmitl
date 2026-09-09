# Module 7 · สถาปัตยกรรมเชิงลึกของ Model Context Protocol

**09:00 – 10:15** · เป้าหมาย: เข้าใจว่า MCP แก้ปัญหาอะไร และประกอบด้วยอะไรบ้าง

---

## 1. ปัญหาที่ MCP แก้ — M × N

ก่อนมี MCP: AI client ทุกตัวต้องเขียน integration กับระบบทุกตัวเอง

```mermaid
flowchart LR
    subgraph B["ก่อนมี MCP — M × N"]
        C1["Claude"] --> S1["PostgreSQL"]
        C1 --> S2["Neo4j"]
        C1 --> S3["OpenSearch"]
        C2["Cursor"] --> S1
        C2 --> S2
        C2 --> S3
        C3["แอปของเรา"] --> S1
        C3 --> S2
        C3 --> S3
    end
```

หลังมี MCP: เขียน server ครั้งเดียว client ทุกตัวใช้ได้

```mermaid
flowchart LR
    subgraph A["มี MCP — M + N"]
        C1["Claude Desktop"] --> M["MCP Server"]
        C2["Cursor"] --> M
        C3["Agent API ของเรา"] --> M
        M --> S1["PostgreSQL"]
        M --> S2["Neo4j"]
        M --> S3["OpenSearch"]
    end
```

> **นี่คือเหตุผลที่ทั้ง 3 วันมุ่งมาที่นี่**: MCP Server ที่สร้างบ่ายนี้ ใช้ได้ทั้งกับ agent ที่เขียนเมื่อวาน และกับ Claude Desktop ในเครื่องตัวเอง โดยไม่ต้องเขียนอะไรเพิ่ม

---

## 2. JSON-RPC 2.0 — ภาษากลาง

MCP ใช้ JSON-RPC 2.0 เป็นรูปแบบข้อความ

```mermaid
sequenceDiagram
    participant C as MCP Client
    participant S as MCP Server

    C->>S: initialize (บอกความสามารถของตัวเอง)
    S-->>C: capabilities + protocolVersion
    C->>S: notifications/initialized
    C->>S: tools/list
    S-->>C: รายการ tool + schema
    C->>S: resources/list
    S-->>C: รายการ resource
    Note over C,S: พร้อมทำงาน
    C->>S: tools/call {name, arguments}
    S-->>C: ผลลัพธ์
```

**หน้าตาข้อความจริง**

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call",
 "params":{"name":"search_tickets","arguments":{"site_code":"NBI","range":"last_7d"}}}
```

```json
{"jsonrpc":"2.0","id":3,
 "result":{"content":[{"type":"text","text":"{...}"}],"isError":false}}
```

| องค์ประกอบ | ความหมาย |
|---|---|
| `jsonrpc` | ต้องเป็น `"2.0"` เสมอ |
| `id` | จับคู่ request กับ response — ใช้ทำ concurrent ได้ |
| `method` | สิ่งที่ต้องการ |
| ไม่มี `id` | = notification ไม่ต้องการคำตอบ |

---

## 3. สามองค์ประกอบหลัก

```mermaid
flowchart TB
    subgraph MCP["MCP Server"]
        T["**Tools**<br/>สิ่งที่โมเดล *เรียก* เพื่อให้เกิดอะไรขึ้น<br/>โมเดลเป็นคนเลือกเอง"]
        R["**Resources**<br/>สิ่งที่โมเดล *อ่าน* เพื่อเข้าใจโลก<br/>ปกติแอปเป็นคนเลือกให้"]
        P["**Prompts**<br/>เทมเพลตคำสั่งสำเร็จรูป<br/>ผู้ใช้เป็นคนเลือก"]
    end
```

| | Tools | Resources | Prompts |
|---|---|---|---|
| ใครควบคุม | โมเดล | แอปพลิเคชัน | ผู้ใช้ |
| มีผลข้างเคียง | อาจมี | ไม่มี | ไม่มี |
| ตัวอย่างในโปรเจกต์นี้ | `search_tickets` | `schema://overview`, `clock://now` | `diagnose_repeated_complaints` |

### ทำไมต้องแยก Resource ออกจาก Tool

`schema://overview` เป็น Resource ไม่ใช่ Tool เพราะโมเดลควร **อ่านก่อนเริ่มคิด** ไม่ใช่ต้องตัดสินใจว่าจะเรียกหรือไม่

ผลที่ได้จริง: โมเดลที่อ่าน schema แล้วจะเลิกเดาชื่อ column และเลิกแต่งตารางที่ไม่มีอยู่

`clock://now` เป็นตัวอย่างที่ชัดที่สุด — โมเดลไม่รู้ว่าวันนี้วันที่เท่าไหร่ ถ้าไม่บอกมันจะกรองช่วงเวลาผิดอย่างมั่นใจ

---

## 4. Transport

```mermaid
flowchart LR
    subgraph ST["stdio"]
        A1["Client"] <-->|"stdin/stdout"| A2["Server<br/>(กระบวนการลูก)"]
    end
    subgraph HT["Streamable HTTP"]
        B1["Client"] <-->|"POST /mcp<br/>endpoint เดียว"| B2["Server<br/>(บริการบนเครือข่าย)"]
    end
```

| | stdio | Streamable HTTP |
|---|---|---|
| ใช้กับ | Claude Desktop, Cursor | บริการบนเครือข่าย |
| ตัวตน | client เปิดกระบวนการเอง | ต้องมี auth |
| ในโปรเจกต์นี้ | `--transport stdio` | `--transport streamable-http` |

> ⚠️ **stdout เป็นของโปรโตคอล** เวลารันแบบ stdio ห้าม `print()` ลง stdout เด็ดขาด ให้ log ลง stderr
> เป็นบั๊กที่เจอบ่อยที่สุดของคนเขียน MCP server ครั้งแรก

---

## 5. spec เปลี่ยนอะไรมาบ้าง (สำคัญ)

MCP ใช้ **วันที่เป็นเลขเวอร์ชัน** ไม่ใช่ 1.0/2.0

```bash
make protocol-version
```

| เวอร์ชัน | เปลี่ยนอะไร | กระทบเราไหม |
|---|---|---|
| 2024-11-05 | รุ่นแรก · stdio + HTTP+SSE (สอง endpoint) | — |
| **2025-03-26** | **Streamable HTTP** แทน HTTP+SSE · **Tool annotations** · OAuth 2.1 | ✅ ใช้ตัวใหม่ |
| **2025-06-18** | **Structured tool output** · **Elicitation** · ยกเลิก JSON-RPC batching | ✅ ใช้ทั้งสองฟีเจอร์ |

### กับดักที่จะเจอเวลาไปหาตัวอย่างบนอินเทอร์เน็ต

ตัวอย่างเก่าจำนวนมากยังใช้ **HTTP+SSE แบบสอง endpoint** ซึ่งเป็นของที่เลิกใช้แล้ว
ถ้าเห็นโค้ดที่มีทั้ง `/sse` และ `/messages` แสดงว่าเป็นของก่อน 2025-03-26

### ฟีเจอร์ใหม่ที่โปรเจกต์นี้ใช้จริง

| ฟีเจอร์ | ใช้ทำอะไร |
|---|---|
| Tool annotations | ประกาศ `readOnlyHint` ให้ client รู้ว่าตัวไหนปลอดภัย |
| Structured output | tool คืน JSON ตาม schema ไม่ใช่ text ก้อนเดียว |
| **Elicitation** | server ถามผู้ใช้กลับกลางคัน → ตรงกับคำถามหมวด L5 |

---

## 6. ภาพรวมของ server ที่จะสร้างบ่ายนี้

```mermaid
flowchart TB
    subgraph S["MCP Server — nt-network"]
        T["Tools 19 ตัว<br/>tickets · network · logs · reports"]
        R["Resources<br/>schema:// · clock:// · files://"]
        P["Prompts 5 ตัว"]
        G["Guardrails"]
    end
    T --> G
    R --> G
    G --> PG[(PostgreSQL)]
    G --> NEO[(Neo4j)]
    G --> OS[(OpenSearch)]
    CL["Claude Desktop / Cursor"] -->|stdio| S
    API["Agent API"] -->|streamable-http| S
```

---

## 7. ต่อไป

→ [Lab 4: ดู JSON-RPC ที่วิ่งจริง](lab4-jsonrpc-inspect.md)
