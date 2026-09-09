"""LLM client for a local, OpenAI-compatible endpoint.

Two things make this file worth reading:

1. Structured output without native tool calling.
   Gemma is not built around a function-calling API the way some models are.
   Rather than fight that, the agent asks for JSON constrained by a schema and
   parses it. This is the same technique taught in Module 3, and it works with
   any model behind any OpenAI-compatible gateway - which is precisely why the
   workshop teaches it instead of a vendor-specific tool API.

2. Cost is measured in GPU time, not currency.
   A local model has no per-token price, so the meaningful numbers are latency,
   tokens per second and how much context is being carried. Those are what the
   UI displays.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, AsyncIterator

import httpx  # เพิ่มเข้ามาเพื่อจัดการเรื่อง SSL
from openai import AsyncOpenAI
from pydantic import BaseModel

BASE_URL = "https://openrouter.ai/api/v1"
API_KEY = ""
MODEL = "openai/gpt-4o-mini"
MODEL_FAST = "openai/gpt-4o-mini"
TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
GUIDED = os.getenv("LLM_GUIDED_DECODING", "true").lower() == "true"

# สร้าง AsyncClient ที่ปิดการเช็กใบรับรอง SSL
custom_client = httpx.AsyncClient(verify=False)

# นำ client พิเศษใส่เข้าไปใน AsyncOpenAI
client = AsyncOpenAI(
    base_url=BASE_URL, 
    api_key=API_KEY, 
    timeout=TIMEOUT,
    http_client=custom_client
)

class LLMStats:
    """Accumulates usage across one request so the UI can show real numbers."""

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.latency_ms = 0
        self.calls = 0

    def record(self, usage, elapsed_ms: int) -> None:
        self.calls += 1
        self.latency_ms += elapsed_ms
        if usage:
            self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0

    def as_dict(self) -> dict:
        total = self.prompt_tokens + self.completion_tokens
        seconds = self.latency_ms / 1000 or 1
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": total,
            "latency_ms": self.latency_ms,
            "tokens_per_second": round(self.completion_tokens / seconds, 1),
            "llm_calls": self.calls,
        }


async def complete(
    messages: list[dict],
    stats: LLMStats | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> str:
    """Plain completion, no schema."""
    started = time.time()
    response = await client.chat.completions.create(
        model=model or MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if stats:
        stats.record(response.usage, int((time.time() - started) * 1000))
    return response.choices[0].message.content or ""


async def complete_structured(
    messages: list[dict],
    schema: type[BaseModel],
    stats: LLMStats | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    max_retries: int = 3,
) -> BaseModel:
    """Return a validated instance of `schema`, retrying on invalid output.

    The retry is not a blind repeat: the validation error is fed back to the
    model, which is what turns a failed parse into a corrected one. This is the
    auto-retry mechanism built in Workshop 1, promoted into the agent.
    """
    json_schema = schema.model_json_schema()
    conversation = list(messages)

    kwargs: dict[str, Any] = {}
    if GUIDED:
        # Ask the gateway to constrain generation. Ollama accepts a schema in
        # `format`; vLLM exposes the same capability through response_format.
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": json_schema, "strict": True},
        }

    last_error = ""
    for attempt in range(max_retries):
        started = time.time()
        try:
            response = await client.chat.completions.create(
                model=model or MODEL,
                messages=conversation,
                temperature=temperature,
                max_tokens=2048,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            # A gateway that does not understand response_format fails here.
            # Fall back to prompting for JSON rather than giving up entirely.
            if kwargs:
                kwargs = {}
                conversation = conversation + [{
                    "role": "system",
                    "content": ("Respond with a single JSON object matching this schema. "
                                "No prose, no markdown fence.\n"
                                + json.dumps(json_schema, ensure_ascii=False)),
                }]
                continue
            raise RuntimeError(f"LLM request failed: {exc}") from exc

        if stats:
            stats.record(response.usage, int((time.time() - started) * 1000))

        raw = (response.choices[0].message.content or "").strip()
        # Models sometimes wrap JSON in a markdown fence despite instructions.
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            raw = raw[4:] if raw.startswith("json") else raw

        try:
            return schema.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            conversation = conversation + [
                {"role": "assistant", "content": raw[:1000]},
                {
                    "role": "user",
                    "content": (
                        f"That did not validate against the schema.\n"
                        f"Error: {last_error}\n"
                        f"Return corrected JSON only."
                    ),
                },
            ]

    raise ValueError(
        f"Could not obtain valid {schema.__name__} after {max_retries} attempts. "
        f"Last error: {last_error}"
    )


async def stream(
    messages: list[dict],
    stats: LLMStats | None = None,
    model: str | None = None,
    temperature: float = 0.3,
) -> AsyncIterator[str]:
    """Stream a completion token by token.

    stream_options.include_usage asks the gateway to send a final chunk with
    token counts. Not every gateway implements it - when it is missing the UI
    falls back to counting locally with the model's own tokenizer.
    """
    started = time.time()
    try:
        response = await client.chat.completions.create(
            model=model or MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=2048,
            stream=True,
            stream_options={"include_usage": True},
        )
    except TypeError:
        response = await client.chat.completions.create(
            model=model or MODEL, messages=messages,
            temperature=temperature, max_tokens=2048, stream=True,
        )

    async for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
        if getattr(chunk, "usage", None) and stats:
            stats.record(chunk.usage, int((time.time() - started) * 1000))
