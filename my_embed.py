import os
import httpx
import psycopg
from dotenv import load_dotenv

load_dotenv()

PG = "postgresql://mpls:mpls_dev_password@localhost:5432/mplsdb"

# 1. เปลี่ยนตัวแปร EMB และ MODEL ให้เป็นของ OpenRouter (ตามที่คุณต้องการเปลี่ยน)
EMB = "https://openrouter.ai/api/v1/embeddings"
MODEL = "openai/text-embedding-3-small"
API_KEY = os.getenv("LLM_API_KEY", "")

def embed_batch(texts: list[str]) -> list[list[float]]:
    # 2. เพิ่ม headers สำหรับยืนยันตัวตนของ OpenRouter
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "HTTP-Referer": "http://localhost",
        "X-Title": "MCP Workshop"
    }
    
    # 3. ส่ง dimensions: 768 ไปด้วย เพื่อให้ขนาดตรงกับตารางเดิม
    r = httpx.post(
        EMB, 
        json={
            "model": MODEL, 
            "input": texts,
            "dimensions": 1536
        }, 
        headers=headers, 
        timeout=60
    )
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda d: d["index"])   # อย่าลืมเรียงลำดับ
    return [d["embedding"] for d in data]

with psycopg.connect(PG) as conn:
    cur = conn.cursor()
    cur.execute("SELECT ticket_id, title, description FROM tickets ORDER BY ticket_id")
    rows = cur.fetchall()

    BATCH = 32           # ยิงทีละ 32 แถว
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i+BATCH]
        vecs = embed_batch([f"{t}\n\n{d}" for _, t, d in chunk])
        for (tid, _, _), v in zip(chunk, vecs):
            # แปลง vector เป็น string สำหรับใส่ใน postgres
            vector_str = "[" + ",".join(map(str, v)) + "]"
            cur.execute("UPDATE tickets SET embedding = %s::vector WHERE ticket_id = %s",
                        (vector_str, tid))
        conn.commit()
        print(f"{i+len(chunk)}/{len(rows)}")