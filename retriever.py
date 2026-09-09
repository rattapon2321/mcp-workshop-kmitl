from neo4j import GraphDatabase

# 1. เชื่อมต่อกับ Neo4j Database (ปรับ Uri, User, Password ตามที่คุณใช้งานจริง)
URI = "bolt://localhost:7687"  # หรือค่า uri ของคุณ
AUTH = ("neo4j", "neo4j_dev_password")    # เปลี่ยนรหัสผ่านให้ตรงกับของคุณ

driver = GraphDatabase.driver(URI, auth=AUTH)
session = driver.session()

# 2. ฟังก์ชันค้นหาอุปกรณ์
def search_devices(query_vector):
    query = """
        CALL db.index.vector.queryNodes('device_embedding', 3, $vec)
        YIELD node, score 
        RETURN node.device_id, score
    """
    # สั่งรันผ่าน session ที่เราสร้างไว้ข้างบน
    result = session.run(query, vec=query_vector)
    return [record for record in result]

print("รัน Retriever สำเร็จแล้วจ้า!")

# 3. ทดสอบเรียกใช้งาน
dummy_vector = [0.1] * 1536 
results = search_devices(dummy_vector)
print("ผลการค้นหาจาก Neo4j:", results)

# ปิด session เมื่อเลิกใช้งาน
session.close()
driver.close()