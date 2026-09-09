# ระบบไฟล์จำลอง (Mock Filesystem)

โฟลเดอร์นี้ถูก expose ผ่าน MCP Resource `files://index` และ `files://read/{path}`
แบบ **อ่านอย่างเดียวและอยู่ใน sandbox**

ใช้สอน Workshop 3 ส่วน Resource Setup — การเปิดให้ AI อ่านระบบไฟล์อย่างปลอดภัย

## กติกาความปลอดภัย 3 ข้อ

1. **Root เดียว** — path ถูก resolve แล้วเทียบว่าอยู่ใต้ root จริงไหม จับได้ทั้ง `../` และ symlink ที่ชี้ออกนอก
2. **Allowlist นามสกุล** — เฉพาะไฟล์ข้อความ (`.md .txt .cfg .conf .json .yaml .yml`)
3. **จำกัดขนาด** — ไฟล์ยาวถูกตัดพร้อมข้อความแจ้ง ไม่ปล่อยให้ท่วม context

## ลองโจมตีดู (โจทย์ที่ 5)

```
files://read/../../.env
files://read/../../../etc/passwd
```

ทั้งคู่ต้องถูกปฏิเสธและถูกบันทึกลง audit log
