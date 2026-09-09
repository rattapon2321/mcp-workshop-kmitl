# มาตรฐานค่า MTU ในโครงข่าย

| ประเภทลิงก์ | MTU มาตรฐาน |
|---|---|
| Core to Core | 9000 |
| Core to PE | 9000 |
| PE to APE | 9000 |
| APE to LPE | 1500 |
| LPE to Customer | 1500 |

## เหตุผล
โครงข่าย backbone ใช้ jumbo frame เพื่อรองรับ MPLS label stack และ overhead ของ VPN
โดยไม่ต้อง fragment

## ข้อผิดพลาดที่พบบ่อยที่สุด
อุปกรณ์ใหม่จากโรงงานมักตั้ง MTU เริ่มต้นที่ 1500
**หลังเปลี่ยนอุปกรณ์ทุกครั้ง ต้องตรวจสอบ MTU ของทุก interface ที่เป็นลิงก์ backbone**

ถ้า MTU สองฝั่งไม่เท่ากัน ISIS จะไม่สามารถสร้าง adjacency ได้
เพราะ hello PDU ถูกส่งแบบ padded เต็มขนาด MTU และจะถูก drop ที่ฝั่งที่ MTU เล็กกว่า

อาการที่เห็น: link อยู่ในสถานะ up ทั้งสองฝั่ง แต่ adjacency ค้างที่ Init หรือ Down
