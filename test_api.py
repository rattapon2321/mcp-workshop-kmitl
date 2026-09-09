import httpx
from openai import OpenAI

print("กำลังทดสอบเชื่อมต่อ OpenRouter (แบบข้าม SSL Bug)...")

# สร้าง client พิเศษที่สั่งปิดการเช็กใบรับรอง (verify=False)
custom_client = httpx.Client(verify=False)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="",
    http_client=custom_client # ยัด client พิเศษใส่เข้าไป
)

response = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[
        {"role": "user", "content": "สวัสดีสั้นๆ 1 ประโยค"}
    ]
)
print("✅ เชื่อมต่อสำเร็จ! AI ตอบว่า:", response.choices[0].message.content)