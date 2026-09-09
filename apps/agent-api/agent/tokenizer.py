"""Token counting for the model actually in use.

The trap this module exists to expose: tiktoken is OpenAI's BPE tokenizer.
Using it to count tokens for Gemma produces a number that is simply wrong,
and wrong in different ways for Thai and English text.

Module 1 has participants compare three counts of the same sentence:

    pythainlp.word_tokenize  words a human recognises
    Gemma SentencePiece      tokens the model actually sees   <- the real number
    tiktoken                 what you get if you use the wrong tokenizer

For Thai the three numbers are far apart, which is the whole lesson: a
tokenizer belongs to a model, and swapping models means recounting.
"""

from __future__ import annotations

import functools
import os

MODEL_ID = os.getenv("TOKENIZER_MODEL_ID", "unsloth/gemma-2-9b-it")


@functools.lru_cache
def _gemma_tokenizer():
    try:
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained(MODEL_ID)
    except Exception as e:
        print(f"\n🚨 [DEBUG Error โหลด Tokenizer]: {e}\n") # สั่งให้โชว์ Error ออกมา
        return None


@functools.lru_cache
def _tiktoken_encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001
        return None


def count(text: str) -> int:
    """Best available token count for the model in use.

    Falls back to a character heuristic when the tokenizer cannot be loaded,
    because a rough number keeps the UI meter working offline. The heuristic is
    tuned for mixed Thai/English: Thai characters cost noticeably more.
    """
    tokenizer = _gemma_tokenizer()
    if tokenizer is not None:
        return len(tokenizer.encode(text, add_special_tokens=False))

    thai = sum(1 for ch in text if "฀" <= ch <= "๿")
    other = len(text) - thai
    return int(thai / 1.6 + other / 4) + 1


def compare(text: str) -> dict:
    """Three-way comparison used by Module 1 and the token meter."""
    result: dict = {"text_length": len(text)}

    tokenizer = _gemma_tokenizer()
    result["gemma_tokens"] = (
        len(tokenizer.encode(text, add_special_tokens=False)) if tokenizer else None
    )

    encoder = _tiktoken_encoder()
    result["tiktoken_tokens"] = len(encoder.encode(text)) if encoder else None

    try:
        from pythainlp.tokenize import word_tokenize

        result["thai_words"] = len(word_tokenize(text, engine="newmm"))
    except Exception:  # noqa: BLE001
        result["thai_words"] = None

    if result["gemma_tokens"] and result["tiktoken_tokens"]:
        result["tiktoken_error_pct"] = round(
            (result["tiktoken_tokens"] - result["gemma_tokens"])
            / result["gemma_tokens"] * 100, 1
        )
    if result["gemma_tokens"] and result["thai_words"]:
        result["tokens_per_word"] = round(result["gemma_tokens"] / result["thai_words"], 2)

    return result
