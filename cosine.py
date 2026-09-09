import httpx
from openai import OpenAI

print("กำลังเชื่อมต่อ OpenRouter เพื่อสร้าง Embedding...")

# 1. ตั้งค่าเชื่อมต่อ OpenRouter (ใช้คีย์ที่ถูกต้อง)
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="",  # คีย์ที่ใช้งานได้จริง
    http_client=httpx.Client(verify=False)
)

def embed_batch(texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(
        model="openai/text-embedding-3-small",
        input=texts
    )
    return [item.embedding for item in response.data]

# 2. ทดสอบแปลงข้อความ
q = embed_batch(["ลูกค้าบ่นว่าอินเทอร์เน็ตหลุดบ่อย"])[0]

print("✅ แปลง Embedding สำเร็จ!")
print("ความยาวมิติเวกเตอร์:", len(q)) # ควรจะได้ 1536
print("ตัวอย่างข้อมูลเวกเตอร์ 5 ค่าแรก:", q[:5])
