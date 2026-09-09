# เช็คลิสต์สำหรับทีมงาน

> สำหรับวิทยากรและทีมสนับสนุน ไม่ใช่สำหรับผู้เรียน

---

## T-7 วัน

- [ ] ส่ง [instructions/00-prerequisites.md](instructions/00-prerequisites.md) ให้ผู้เรียน
- [ ] ส่งแบบสอบถามก่อนอบรม
- [ ] แจ้ง URL และ API key ของ LLM ภายใน
- [ ] แจ้งวิธีต่อ VPN (ถ้าต้องใช้)
- [ ] ยืนยันว่าผู้เรียนทุกคนมีสิทธิ์ติดตั้ง Docker บนเครื่อง

---

## T-3 วัน — ทดสอบ LLM (สำคัญที่สุด)

จุดที่ workshop สะดุดบ่อยที่สุดคือ LLM ไม่พร้อม ทดสอบทั้ง 3 ข้อจากเครื่องที่ผู้เรียนจะใช้จริง

- [ ] **ยิงถึง**
  ```bash
  curl -s $LLM_BASE_URL/models -H "Authorization: Bearer $LLM_API_KEY"
  ```
- [ ] **รองรับ guided decoding** — ดู [reference/local-llm-ollama-vllm.md](instructions/reference/local-llm-ollama-vllm.md) หัวข้อ 5.2
  ถ้าไม่รองรับ ต้องแจ้งผู้เรียนให้ตั้ง `LLM_GUIDED_DECODING=false`
- [ ] **คืน usage ตอน stream** — ถ้าไม่ ระบบจะนับ token เองด้วย tokenizer
- [ ] **ทดสอบ embedding endpoint** และยืนยันว่าได้ 768 มิติ
- [ ] **ทดสอบภาระ** — ให้ 5 คนยิงพร้อมกัน วัดว่าคนสุดท้ายรอนานแค่ไหน
      ถ้าเกิน 30 วินาที ต้องเพิ่ม instance หรือเปลี่ยนไป vLLM

---

## T-1 วัน

- [ ] `make reset && make up && make verify` บนเครื่องวิทยากร → ต้อง `ALL CHECKS PASSED`
- [ ] `make embed-tickets && make embed-devices` → ไม่มี warning
- [ ] `make test` ผ่านทั้งหมด
- [ ] `make demo` เปิดได้ ทดสอบคำถามทั้ง 4 ข้อในสคริปต์เดโม
- [ ] **`make demo-record`** บันทึก trace สำหรับโหมด replay
- [ ] `make demo-offline` ทดสอบว่าเล่นได้โดยไม่ต้องมี LLM
- [ ] `make demo-export` เตรียมไฟล์ `.tar` เผื่อเครื่องหน้างานไม่มีเน็ต
- [ ] เตรียม USB มี image ทั้งหมด เผื่อเน็ตห้องอบรมช้า
- [ ] พิมพ์ [reference/cheatsheet.md](instructions/reference/cheatsheet.md) แจกผู้เรียน

---

## เช้าวันอบรมทุกวัน

- [ ] **`make reseed`** ← ทำทุกเช้า เพื่อให้ timestamp สดใหม่
      ไม่งั้นคำถาม "24 ชั่วโมงที่ผ่านมา" จะไม่เจออะไร
- [ ] `make verify` ยืนยันอีกครั้ง
- [ ] **`make demo-record`** ถ้าจะใช้โหมด replay (ต้องทำหลัง reseed ทุกครั้ง)
- [ ] ทดสอบ LLM endpoint อีกครั้ง
- [ ] อุ่นเครื่องโมเดล — ยิงคำขอเปล่า 1 ครั้ง ไม่งั้นคำถามแรกต่อหน้าผู้เรียนจะช้ามาก

---

## วันที่ 1

- [ ] เปิดคอร์สด้วย **เดโม 12 นาที** (สคริปต์อยู่ที่ `docker/demo/README.md`)
- [ ] ช่วยทุกคนให้ `make verify` ผ่านก่อน 10:00 น.
- [ ] แจ้งว่าเฉลยอยู่ที่ `solutions/` และอธิบายว่าทำไมไม่ควรเปิดก่อน
- [ ] แนะนำให้ใช้ `LLM_MODEL_FAST` ระหว่างทำ lab

---

## วันที่ 2

- [ ] เตือนเรื่องลำดับ: **Intent ต้องมาก่อน Memory เสมอ**
- [ ] ตรวจว่าทุกคนทำ Lab 1 เสร็จแล้ว (ไม่งั้น semantic search จะพัง)
- [ ] เตรียม MailHog ให้เปิดได้ทุกเครื่อง

---

## วันที่ 3

- [ ] ตรวจว่าผู้เรียนติดตั้ง Claude Desktop หรือ Cursor แล้ว
- [ ] เตือนเรื่อง **absolute path** ใน config
- [ ] เตือนเรื่อง **ห้าม print ลง stdout** เมื่อรันแบบ stdio
- [ ] `make protocol-version` แสดงให้ดูตอนต้น Module 7
- [ ] เตรียมเวลาสำหรับ Workshop 3 ให้พอ — เป็นช่วงที่มักไม่ทัน

---

## หลังอบรม

- [ ] รวบรวมผลงานโจทย์ทั้ง 6 ข้อ
- [ ] สรุปว่าใครติดตรงไหน เพื่อปรับรอบถัดไป
- [ ] **เก็บ baseline metric** ตามที่ระบุใน [day3/wrap-up](instructions/day3/wrap-up-mpls-llm.md)
- [ ] แบ่งงานสำหรับ MPLS LLM ตามตารางในไฟล์เดียวกัน
- [ ] นัดหมายติดตามผลครั้งที่ 1

---

## แผนสำรองเมื่อเกิดปัญหา

| ปัญหา | แผนสำรอง |
|---|---|
| LLM ล่มทั้งวัน | ใช้ `make demo-offline` สอนจาก trace ที่บันทึกไว้ + เน้นอ่านโค้ด |
| เน็ตห้องอบรมช้า | ใช้ image จาก USB · `docker load -i` |
| เครื่องผู้เรียนรัน Docker ไม่ไหว | จับคู่ทำงาน หรือเตรียมเครื่องกลางให้ SSH เข้า |
| GPU คิวยาวมาก | ทุกคนใช้ `gemma3:4b` ระหว่าง lab |
| Workshop 3 ไม่ทัน | ให้ทำ Resource Setup ให้เสร็จก่อน แล้วให้ Tool Setup เป็นการบ้าน |
