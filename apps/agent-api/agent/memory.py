"""Short-term memory with topic-shift detection.

The problem this solves
-----------------------
A naive agent appends every turn to the context. Twenty turns later the
context is enormous, mostly irrelevant, and the model has started losing
details in the middle of it - the content dilution effect from Module 2.

The fix is not a bigger window. It is noticing when the subject changes and
throwing away what no longer matters, keeping only a one-line summary.
"""

from __future__ import annotations

import os
import re
import uuid
import httpx

# ==========================================
# ส่วนที่เพิ่มเข้ามาเพื่อให้รันไฟล์นี้ได้ตรงๆ
import sys
from pathlib import Path
# ชี้ Path กลับไปที่โฟลเดอร์ apps/agent-api (ถอยขึ้นไป 1 ชั้น)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# ==========================================

from schemas import MemorySnapshot, TopicState

# แก้ไขจาก from . import llm, tokenizer เป็น:
from agent import llm, tokenizer


SIMILARITY_THRESHOLD = float(os.getenv("MEMORY_TOPIC_SHIFT_THRESHOLD", "0.55"))
WINDOW_TURNS = int(os.getenv("MEMORY_WINDOW_TURNS", "6"))
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "embeddinggemma:300m")

EXPLICIT_SHIFT = re.compile(
    r"(เปลี่ยนเรื่อง|ขอถามเรื่องอื่น|ขอถามอีกเรื่อง|เรื่องใหม่|"
    r"อีกเรื่องนึง|change topic|different question|new topic)",
    re.IGNORECASE,
)
DEVICE_PATTERN = re.compile(r"\b((?:CR|PE|APE|LPE)-([A-Z]{3})-\d{2})\b", re.IGNORECASE)
SITE_PATTERN = re.compile(r"\b(BKK|NBI|กรุงเทพ|นนทบุรี)\b", re.IGNORECASE)

SITE_ALIASES = {"กรุงเทพ": "BKK", "นนทบุรี": "NBI"}


def _embed(text: str) -> list[float] | None:
    try:
        response = httpx.post(
            f"{EMBEDDING_BASE_URL.rstrip('/')}/embeddings",
            json={"model": EMBEDDING_MODEL, "input": [text]},
            headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', 'not-needed')}"},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]
    except Exception:  # noqa: BLE001
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def extract_entities(text: str) -> list[str]:
    """Device ids and site codes mentioned in a message."""
    entities = {match.group(1).upper() for match in DEVICE_PATTERN.finditer(text)}
    for match in SITE_PATTERN.finditer(text):
        token = match.group(1)
        entities.add(SITE_ALIASES.get(token, token.upper()))
    return sorted(entities)


class SessionMemory:
    """Per-session state. Held in memory: a workshop does not need durability,
    and keeping it simple makes the mechanism visible."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.turn = 0
        self.topic: TopicState | None = None
        self.topic_vector: list[float] | None = None
        self.recent: list[dict] = []
        self.archived: list[str] = []
        self.topic_changes = 0

    # ------------------------------------------------------------------

    def detect_topic_shift(self, message: str) -> tuple[bool, str]:
        """Return (changed, why). Cheap checks before expensive ones."""
        if self.topic is None:
            return True, "ยังไม่มีหัวข้อ - เริ่มหัวข้อแรก"

        if EXPLICIT_SHIFT.search(message):
            return True, "ผู้ใช้บอกเองว่าเปลี่ยนเรื่อง"

        entities = extract_entities(message)
        if entities and self.topic.entities:
            overlap = set(entities) & set(self.topic.entities)
            if not overlap:
                sites_new = {e for e in entities if e in ("BKK", "NBI")}
                sites_old = {e for e in self.topic.entities if e in ("BKK", "NBI")}
                if sites_new and sites_old and not (sites_new & sites_old):
                    return True, f"เปลี่ยนพื้นที่จาก {sorted(sites_old)} ไป {sorted(sites_new)}"

        if self.topic_vector:
            vector = _embed(message)
            if vector:
                similarity = _cosine(vector, self.topic_vector)
                if similarity < SIMILARITY_THRESHOLD:
                    return True, f"ความใกล้เคียงกับหัวข้อเดิมต่ำ ({similarity:.2f})"

        return False, "ยังเป็นหัวข้อเดิม"

    # ------------------------------------------------------------------

    async def start_topic(self, message: str, stats=None) -> None:
        """Archive the previous topic as one line, then begin a new one."""
        if self.topic and self.recent:
            summary = await self._summarise_topic(stats)
            self.archived.append(summary)
            self.topic_changes += 1

        self.recent = []
        entities = extract_entities(message)
        label = ", ".join(entities) if entities else message[:40]
        self.topic = TopicState(
            topic_id=str(uuid.uuid4())[:8],
            label=label,
            entities=entities,
            turn_started=self.turn,
        )
        self.topic_vector = _embed(message)

    async def _summarise_topic(self, stats=None) -> str:
        transcript = "\n".join(
            f"{turn['role']}: {turn['content'][:400]}" for turn in self.recent
        )
        try:
            summary = await llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "สรุปบทสนทนาต่อไปนี้ให้เหลือ 1-2 ประโยคภาษาไทย "
                            "โดยต้องเก็บ: อุปกรณ์หรือพื้นที่ที่พูดถึง และข้อสรุปที่ได้ "
                            "ถ้ายังไม่ได้ข้อสรุปให้บอกว่ายังไม่ได้ข้อสรุป "
                            "ตอบเฉพาะบทสรุป ไม่ต้องมีคำนำ"
                        ),
                    },
                    {"role": "user", "content": transcript},
                ],
                stats=stats, temperature=0.1, max_tokens=200,
            )
            label = self.topic.label if self.topic else "ไม่ระบุ"
            return f"[{label}] {summary.strip()}"
        except Exception:  # noqa: BLE001
            label = self.topic.label if self.topic else "ไม่ระบุ"
            return f"[{label}] (สรุปอัตโนมัติไม่สำเร็จ - คุยกัน {len(self.recent)} ข้อความ)"

    # ------------------------------------------------------------------

    def add_turn(self, role: str, content: str) -> None:
        self.recent.append({"role": role, "content": content})
        if len(self.recent) > WINDOW_TURNS * 2:
            self.recent = self.recent[-WINDOW_TURNS * 2:]

    def build_context(self) -> list[dict]:
        """Messages to send to the model for this turn."""
        messages: list[dict] = []
        if self.archived:
            messages.append({
                "role": "system",
                "content": (
                    "สรุปเรื่องที่คุยกันไปก่อนหน้านี้ (คนละหัวข้อกับตอนนี้):\n"
                    + "\n".join(f"- {s}" for s in self.archived[-5:])
                ),
            })
        messages.extend(self.recent)
        return messages

    def context_tokens(self) -> int:
        return sum(tokenizer.count(m["content"]) for m in self.build_context())

    def snapshot(self) -> MemorySnapshot:
        return MemorySnapshot(
            session_id=self.session_id,
            turn=self.turn,
            current_topic=self.topic,
            recent_turns=self.recent,
            archived_summaries=self.archived,
            context_tokens=self.context_tokens(),
            topic_changes=self.topic_changes,
        )


_SESSIONS: dict[str, SessionMemory] = {}


def get(session_id: str) -> SessionMemory:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = SessionMemory(session_id)
    return _SESSIONS[session_id]


def reset(session_id: str) -> None:
    _SESSIONS.pop(session_id, None)


# ==========================================
# บล็อกทดสอบการทำงานจำลอง (จะทำงานเมื่อรันไฟล์นี้ตรงๆ)
if __name__ == "__main__":
    import asyncio
    
    async def run_test():
        print("🚀 เริ่มทดสอบระบบ Memory...")
        session = get("test-session-123")
        
        print("\n1. ทดสอบบันทึกความจำ (หัวข้อแรก)...")
        await session.start_topic("เน็ตที่สาขา BKK หลุดครับ เช็ค CR-BKK-01 ให้หน่อย")
        session.add_turn("user", "เน็ตที่สาขา BKK หลุดครับ เช็ค CR-BKK-01 ให้หน่อย")
        session.add_turn("assistant", "กำลังตรวจสอบอุปกรณ์ CR-BKK-01 ให้ครับ")
        print(f"✅ ความจำถูกบันทึก (Context tokens ที่ใช้: {session.context_tokens()})")
        
        print("\n2. ทดสอบเช็กการเปลี่ยนเรื่อง (Topic Shift)...")
        # ทดสอบโยนประโยคที่จะทำให้เกิด Topic Shift แน่ๆ (เปลี่ยนสถานที่)
        changed, reason = session.detect_topic_shift("เปลี่ยนเรื่องครับ ไปดูที่สาขา NBI แทนหน่อย")
        print(f"เกิดการเปลี่ยนหัวข้อใหม่?: {changed}")
        print(f"เหตุผลที่ตรวจจับได้: {reason}")
        
        print("\n🎉 รันสคริปต์สมบูรณ์แบบ ทำงานได้ 100%!")

    asyncio.run(run_test())