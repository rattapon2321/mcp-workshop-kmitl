"""Intent gate: decide whether a question belongs to this system at all.

Two layers, cheapest first:

  Layer 1  deterministic fast path. Obvious domain terms, or an obviously
           unrelated request, are settled without an LLM call.
  Layer 2  a constrained LLM classification for everything ambiguous.

Why bother, when the model could just answer? Three reasons, in order of
importance:

  1. Refusing early means no tool call, so nothing touches the databases on
     behalf of a question that has no business there.
  2. A 27B model on shared GPUs is the scarcest resource in the room. Not
     spending it on "what's the weather" is a real saving.
  3. The classification is a place to put the distinction between "out of
     scope" and "unclear" - the second deserves a question back, not a refusal.
"""

from __future__ import annotations

import re

from schemas import IntentLabel, IntentResult

from . import llm

# --------------------------------------------------------------------------
# Layer 1: fast path
# --------------------------------------------------------------------------

DOMAIN_TERMS = [
    "ticket", "เคส", "แจ้ง", "ลูกค้า", "วงจร", "circuit", "อุปกรณ์", "device",
    "router", "เราเตอร์", "log", "ล็อก", "interface", "อินเทอร์เฟซ", "mtu",
    "isis", "adjacency", "bgp", "ldp", "mpls", "topology", "โครงข่าย", "เครือข่าย",
    "หลุด", "ล่ม", "ช้า", "down", "up", "flap", "crc", "cpu", "config", "ตั้งค่า",
    "bkk", "nbi", "นนทบุรี", "กรุงเทพ", "core", "สุขภาพ", "health", "maintenance",
    "บำรุงรักษา", "pe-", "ape-", "lpe-", "cr-", "รายงาน", "report", "noc",
]

OFF_DOMAIN_TERMS = [
    "อากาศ", "weather", "หุ้น", "stock", "ลงทุน", "ราคาทอง", "แปลภาษา", "translate",
    "ร้านอาหาร", "restaurant", "เพลง", "หนัง", "ลาพักร้อน", "ลากิจ", "เงินเดือน",
    "สูตรอาหาร", "recipe", "ดวง", "หวย", "กีฬา", "ฟุตบอล",
]

DEVICE_PATTERN = re.compile(r"\b(?:CR|PE|APE|LPE)-[A-Z]{3}-\d{2}\b", re.IGNORECASE)
TICKET_PATTERN = re.compile(r"\bTK-\d{2}-\d{5}\b", re.IGNORECASE)

# Pronouns with no antecedent, and requests with no object, are the signature
# of an ambiguous follow-up.
#
# These match a PREFIX rather than the whole string, because Thai questions
# trail off rather than end: "ดูให้หน่อยว่าปกติไหม" is the same request as
# "ดูให้หน่อย". Anchoring with $ misses every natural phrasing.
#
# Matching loosely is safe here only because the caller requires
# `not domain_hits` as well - "ตรวจให้หน่อยว่า APE-NBI-03 มี log อะไร" starts
# the same way but names a device, so it is never treated as vague.
VAGUE_PATTERNS = [
    # Thai stacks noun classifiers ("อุปกรณ์ตัวนี้" = device + counter +
    # demonstrative), so allow several before the pronoun. No \b at the end:
    # Thai has no spaces, and every Thai character is a word character, so a
    # word boundary never matches mid-sentence.
    re.compile(r"^\s*(?:อุปกรณ์|ตัว|เครื่อง|ใบ|เคส|วงจร|ลิงก์|อันนี้)*\s*(?:นี้|นั้น)"),
    re.compile(r"^\s*(ดูให้|เช็คให้|ตรวจให้|ช่วยดู|ช่วยเช็ค|ช่วยตรวจ)"),
    re.compile(r"^\s*(เป็นไง|เป็นยังไง|ปกติไหม|มีปัญหาอะไร|มีอะไรบ้าง)"),
]


def fast_path(message: str) -> IntentResult | None:
    """Settle the obvious cases without spending a model call."""
    lowered = message.lower().strip()

    # An explicit identifier is unambiguous evidence of domain relevance.
    if DEVICE_PATTERN.search(message) or TICKET_PATTERN.search(message):
        return IntentResult(
            label=IntentLabel.IN_SCOPE, confidence=0.98,
            reason="พบรหัสอุปกรณ์หรือหมายเลข ticket ในคำถาม",
            decided_by="fast_path",
        )

    off_hits = [t for t in OFF_DOMAIN_TERMS if t in lowered]
    domain_hits = [t for t in DOMAIN_TERMS if t in lowered]

    # Only decide off-domain when there is no competing domain signal, so
    # "ส่งรายงาน log ให้ทีมก่อนไปกินข้าว" is not misclassified.
    if off_hits and not domain_hits:
        return IntentResult(
            label=IntentLabel.OUT_OF_SCOPE, confidence=0.95,
            reason=f"คำถามเกี่ยวกับ '{off_hits[0]}' ซึ่งอยู่นอกขอบเขตงานโครงข่าย",
            decided_by="fast_path",
        )

    if len(domain_hits) >= 2:
        return IntentResult(
            label=IntentLabel.IN_SCOPE, confidence=0.9,
            reason=f"พบคำเฉพาะทางในโดเมน: {', '.join(domain_hits[:3])}",
            decided_by="fast_path",
        )

    stripped = message.strip()

    # A demonstrative pronoun is strong evidence of a dangling reference even
    # when a generic domain noun is present: "อุปกรณ์ตัวนี้เป็นยังไง" names no
    # device. A specific identifier would have returned IN_SCOPE above, so
    # reaching here means there is nothing concrete to act on.
    #
    # This is safe to decide aggressively because classify() re-routes a
    # NEEDS_CLARIFICATION verdict to the model whenever conversation history
    # exists - and with history, "ใบนี้" usually does have an antecedent.
    if VAGUE_PATTERNS[0].match(stripped):
        return IntentResult(
            label=IntentLabel.NEEDS_CLARIFICATION, confidence=0.85,
            reason="คำถามอ้างถึงสิ่งที่ยังไม่ได้ระบุว่าคืออะไร",
            missing_information=["สิ่งที่ต้องการให้ตรวจสอบ"],
            decided_by="fast_path",
        )

    # The remaining patterns are ordinary phrasings that only count as vague
    # when nothing in the domain is mentioned at all.
    for pattern in VAGUE_PATTERNS[1:]:
        if pattern.match(stripped) and not domain_hits:
            return IntentResult(
                label=IntentLabel.NEEDS_CLARIFICATION, confidence=0.85,
                reason="คำถามยังไม่ได้ระบุขอบเขตที่ต้องการให้ตรวจสอบ",
                missing_information=["สิ่งที่ต้องการให้ตรวจสอบ"],
                decided_by="fast_path",
            )

    return None


# --------------------------------------------------------------------------
# Layer 2: model classification
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You classify incoming questions for a network operations assistant.

The assistant can answer questions about an IP-MPLS network: trouble tickets,
device configuration, physical topology, routing adjacencies, device logs,
equipment health, customer circuits and operational runbooks. It covers exactly
two sites, BKK and NBI, and ten devices.

Choose exactly one label:

in_scope
    Answerable from the network data. Needs tools.

general_knowledge
    A genuine networking question that needs explanation, not data.
    Example: "what is a router", "how does ISIS work".
    Answer directly, no tools.

needs_clarification
    Relates to the network but is missing something essential - which device,
    which time range, which aspect. Ask rather than guess.
    Do NOT use this label when the conversation history already supplies the
    missing piece.

out_of_scope
    Unrelated to network operations. Weather, translation, HR, finance,
    personal requests.

If the question refers to something mentioned earlier in the conversation,
treat it as in_scope, not as needing clarification.
"""


async def classify(
    message: str,
    history: list[dict] | None = None,
    stats: llm.LLMStats | None = None,
    model: str | None = None,
) -> IntentResult:
    """Classify one message. Fast path first, model only when needed."""
    quick = fast_path(message)
    if quick is not None:
        # Conversation history can rescue a message the fast path called vague.
        if quick.label == IntentLabel.NEEDS_CLARIFICATION and history:
            pass  # fall through to the model, which can see the history
        else:
            return quick

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.append({
            "role": "system",
            "content": "Recent conversation:\n" + "\n".join(
                f"{turn['role']}: {turn['content'][:300]}" for turn in history[-4:]
            ),
        })
    messages.append({"role": "user", "content": message})

    result = await llm.complete_structured(messages, IntentResult, stats=stats, model=model)
    result.decided_by = "llm"
    return result


def refusal_message(result: IntentResult) -> str:
    """Human-facing text for a question the system will not act on."""
    if result.label == IntentLabel.OUT_OF_SCOPE:
        return (
            "ขออภัยครับ คำถามนี้อยู่นอกขอบเขตของระบบ\n\n"
            "ระบบนี้ตอบได้เฉพาะเรื่องโครงข่าย IP-MPLS ได้แก่ "
            "ประวัติ ticket และเหตุเสีย, การตั้งค่าอุปกรณ์, โครงสร้างการเชื่อมต่อ, "
            "log ของอุปกรณ์, คะแนนสุขภาพอุปกรณ์ และวงจรของลูกค้า "
            "โดยครอบคลุมพื้นที่ BKK และ NBI\n\n"
            "ลองถามใหม่ เช่น *\"ตอนนี้มี ticket อะไรค้างอยู่บ้าง\"*"
        )

    missing = "\n".join(f"- {item}" for item in result.missing_information) or "- รายละเอียดเพิ่มเติม"
    options = ""
    if result.suggested_options:
        options = "\n\nตัวเลือก:\n" + "\n".join(f"- {o}" for o in result.suggested_options)
    return f"ขอข้อมูลเพิ่มอีกนิดครับ ยังไม่แน่ใจว่า:\n{missing}{options}"
