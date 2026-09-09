import os
from pathlib import Path

# 1. กำหนดโฟลเดอร์หลักที่เก็บไฟล์รายงาน (Base Directory)
# ใช้ .resolve() เพื่อแปลงเป็น Absolute Path ที่แท้จริงตั้งแต่เริ่มต้น
BASE_REPORT_DIR = Path("/var/data/reports").resolve()

# 2. ระบบ Allowlist (เลือกใช้แบบชื่อไฟล์ หรือ นามสกุลไฟล์ ก็ได้)
ALLOWED_FILES = {
    "sales_2023.pdf",
    "q1_summary.csv",
    "annual_report.txt"
}
ALLOWED_EXTENSIONS = {".pdf", ".csv", ".txt"}

def is_in_allowlist(filename: str) -> bool:
    """ตรวจสอบว่าชื่อไฟล์หรือนามสกุลไฟล์อยู่ใน Allowlist หรือไม่"""
    path = Path(filename)
    
    # ตรวจสอบว่าชื่อไฟล์ตรงกับที่อนุญาตไว้หรือไม่
    if filename in ALLOWED_FILES:
        return True
        
    # หรือตรวจสอบว่านามสกุลไฟล์อยู่ในกลุ่มที่อนุญาตหรือไม่ (ใช้ในกรณีที่ไฟล์มีจำนวนมาก)
    if path.suffix.lower() in ALLOWED_EXTENSIONS:
        return True
        
    return False

def get_safe_path(requested_filename: str) -> Path:
    """
    สร้างและตรวจสอบ Path ให้ปลอดภัย
    ส่งคืน Path object หากปลอดภัย หรือโยน Exception หากตรวจพบความเสี่ยง
    """
    # ด่านที่ 1: ตรวจสอบ Allowlist
    if not is_in_allowlist(requested_filename):
        raise ValueError(f"Access Denied: ไฟล์ '{requested_filename}' ไม่อยู่ใน Allowlist")

    # ด่านที่ 2: สร้างและ Resolve Path 
    # .resolve() จะกำจัด '../' หรือ './' ออก และแปลงเป็น Absolute Path
    requested_path = (BASE_REPORT_DIR / requested_filename).resolve()

    # ด่านที่ 3: ตรวจสอบ Path Traversal
    # เช็คว่า Path สุดท้ายที่ได้ ยังคงอยู่ภายใต้โฟลเดอร์ BASE_REPORT_DIR หรือไม่
    try:
        # .is_relative_to() รองรับใน Python 3.9 ขึ้นไป
        if not requested_path.is_relative_to(BASE_REPORT_DIR):
            raise PermissionError("Security Alert: ตรวจพบความพยายามในการทำ Path Traversal")
    except AttributeError:
        # Fallback สำหรับ Python ต่ำกว่า 3.9
        if BASE_REPORT_DIR not in requested_path.parents:
            raise PermissionError("Security Alert: ตรวจพบความพยายามในการทำ Path Traversal")

    # (Optional) ด่านที่ 4: ตรวจสอบว่าไฟล์มีอยู่จริงบนเซิร์ฟเวอร์หรือไม่
    if not requested_path.is_file():
        raise FileNotFoundError(f"Not Found: ไม่พบไฟล์ '{requested_filename}' ในระบบ")

    return requested_path

# ==========================================
# ตัวอย่างการทดสอบระบบ (Test Cases)
# ==========================================
if __name__ == "__main__":
    # จำลองการสร้างโฟลเดอร์และไฟล์สำหรับทดสอบ (เพื่อให้รันโค้ดดูผลลัพธ์ได้จริง)
    BASE_REPORT_DIR = Path("./temp_reports").resolve()
    BASE_REPORT_DIR.mkdir(exist_ok=True)
    (BASE_REPORT_DIR / "q1_summary.csv").touch()
    (BASE_REPORT_DIR / "sales_2023.pdf").touch()

    test_inputs = [
        "q1_summary.csv",                         # 1. ปลอดภัยและมีไฟล์อยู่จริง
        "sales_2023.pdf",                         # 2. ปลอดภัยและมีไฟล์อยู่จริง
        "secret_budget.xlsx",                     # 3. นามสกุลไม่อยู่ใน Allowlist
        "../etc/passwd",                          # 4. พยายามเจาะระบบ (ไม่อยู่ใน Allowlist)
        "fake_report.pdf/../../../../etc/passwd", # 5. นามสกุลผ่าน Allowlist แต่เป็น Path Traversal
    ]

    print(f"Base Directory: {BASE_REPORT_DIR}\n")
    
    for filename in test_inputs:
        print(f"Requesting: {filename}")
        try:
            safe_path = get_safe_path(filename)
            print(f"  [SUCCESS] อนุญาตให้เข้าถึง: {safe_path}")
        except Exception as e:
            print(f"  [BLOCKED] {type(e).__name__}: {e}")
        print("-" * 50)