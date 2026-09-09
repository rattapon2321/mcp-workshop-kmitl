# OpenSearch seed

| ไฟล์ | หน้าที่ |
|---|---|
| `log_index_template.json` | mapping ของ `network-logs-*` — หนึ่ง document ต่อหนึ่งบรรทัด log |
| `doc_index_template.json` | mapping ของ `network-docs` — เอกสาร Markdown ที่ chunk แล้ว + `knn_vector` 768 มิติ |

## ทำไม log แยก index จาก docs

| | `network-logs-*` | `network-docs` |
|---|---|---|
| ลักษณะข้อมูล | append-only ปริมาณมาก | เปลี่ยนไม่บ่อย ปริมาณน้อย |
| การค้นหา | filter ตามเวลา/อุปกรณ์/ระดับ | semantic search |
| มี vector ไหม | ไม่มี (ไม่คุ้ม) | มี `knn_vector` |
| ของจริงที่ NT | 29 GB/วัน → ต้องทำ ILM | runbook + config |

> การ embed log ทุกบรรทัดเป็นความคิดที่แพงและไม่ได้ผลดี — อธิบายเหตุผลไว้ใน
> `instructions/day3/scale-notes.md`

## ตรวจผลด้วยตนเอง

```bash
curl -s 'localhost:9200/network-logs-*/_count' | python3 -m json.tool
```

```bash
curl -s 'localhost:9200/network-logs-*/_search?size=3&sort=@timestamp:desc' | python3 -m json.tool
```
