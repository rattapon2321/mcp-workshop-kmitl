"""Execute a plan, with loop protection.

Responsibilities:
  - run steps in dependency order, concurrently where the plan allows
  - resolve arguments that depend on earlier results
  - stop the agent from running forever

Loop protection is not a nicety. An agent that can re-plan will, given the
chance, call the same tool with the same arguments indefinitely - especially
when a tool keeps returning "not found" and the model keeps deciding to look
again. Module 6 covers this; the guards below are what actually stop it.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, AsyncIterator

from schemas import Plan, StepResult

from . import mcp_client
from .events import EventType

MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "8"))
MAX_SAME_TOOL_CALLS = int(os.getenv("AGENT_MAX_SAME_TOOL_CALLS", "3"))
STEP_TIMEOUT_SECONDS = float(os.getenv("AGENT_STEP_TIMEOUT_SECONDS", "45"))


class LoopGuard:
    """Three independent stop conditions.

    Any one of them alone can be defeated; together they bound every loop shape
    seen in practice:
      - total step budget       stops slow divergence
      - repeated identical call  stops the tight retry loop
      - repeated tool regardless of arguments stops argument-fuzzing loops
    """

    def __init__(self) -> None:
        self.total_steps = 0
        self.call_signatures: dict[str, int] = {}
        self.tool_counts: dict[str, int] = {}

    def check(self, tool: str, arguments: dict) -> str | None:
        """Return a refusal reason, or None if the call may proceed."""
        self.total_steps += 1
        if self.total_steps > MAX_STEPS:
            return f"เกินจำนวนขั้นตอนสูงสุด ({MAX_STEPS} ขั้น)"

        signature = f"{tool}:{sorted(arguments.items())!r}"
        self.call_signatures[signature] = self.call_signatures.get(signature, 0) + 1
        if self.call_signatures[signature] > 1:
            return f"เรียก {tool} ด้วย argument เดิมซ้ำ"

        self.tool_counts[tool] = self.tool_counts.get(tool, 0) + 1
        if self.tool_counts[tool] > MAX_SAME_TOOL_CALLS:
            return f"เรียก {tool} เกิน {MAX_SAME_TOOL_CALLS} ครั้งในคำถามเดียว"

        return None


def resolve_reference(path: str, results: dict[int, StepResult]) -> Any:
    """Resolve a reference like 'step.1.tickets.0.device_id' against results.

    Supports dictionary keys, list indices, and a bare '*' to collect one field
    from every element of a list - which is what turns "the tickets from step 1"
    into "the device ids to pass to step 2".
    """
    parts = path.split(".")
    if len(parts) < 2 or parts[0] != "step":
        return None

    step_number = int(parts[1])
    if step_number not in results or not results[step_number].ok:
        return None

    value: Any = results[step_number].result
    for part in parts[2:]:
        if value is None:
            return None
        if part == "*":
            # Collect the remaining path from every element.
            remainder = parts[parts.index("*") + 1:]
            if not isinstance(value, list):
                return None
            collected = []
            for item in value:
                current = item
                for key in remainder:
                    current = current.get(key) if isinstance(current, dict) else None
                    if current is None:
                        break
                if current is not None:
                    collected.append(current)
            return collected
        if isinstance(value, list):
            try:
                value = value[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


async def execute(plan: Plan) -> AsyncIterator[tuple[EventType, dict]]:
    """Run a plan, yielding events as steps start and finish.

    Steps whose dependencies are satisfied run concurrently. For a plan where
    two independent lookups feed a third step, this halves the wall clock the
    user waits - and the plan already contains the information needed to know
    that it is safe.
    """
    client = mcp_client.get()
    guard = LoopGuard()
    results: dict[int, StepResult] = {}
    pending = {step.step: step for step in plan.steps}

    while pending:
        runnable = [
            step for step in pending.values()
            if all(dep in results for dep in step.depends_on)
        ]
        if not runnable:
            # Every remaining step waits on something that never completed.
            for step in pending.values():
                results[step.step] = StepResult(
                    step=step.step, tool=step.tool, ok=False, duration_ms=0,
                    skipped_reason="ขั้นตอนที่ต้องพึ่งพาไม่สำเร็จ",
                )
                yield EventType.STEP_RESULT, results[step.step].model_dump()
            break

        async def run_one(step) -> StepResult:
            arguments = dict(step.arguments)
            for name, reference in step.argument_from.items():
                resolved = resolve_reference(reference, results)
                if resolved is not None:
                    arguments[name] = resolved

            refusal = guard.check(step.tool, arguments)
            if refusal:
                return StepResult(step=step.step, tool=step.tool, ok=False,
                                  duration_ms=0, skipped_reason=refusal)

            started = time.time()
            try:
                result = await asyncio.wait_for(
                    client.call_tool(step.tool, arguments),
                    timeout=STEP_TIMEOUT_SECONDS,
                )
                elapsed = int((time.time() - started) * 1000)
                if isinstance(result, dict) and "error" in result:
                    return StepResult(step=step.step, tool=step.tool, ok=False,
                                      duration_ms=elapsed, error=str(result["error"]))
                return StepResult(step=step.step, tool=step.tool, ok=True,
                                  duration_ms=elapsed, result=result)
            except asyncio.TimeoutError:
                return StepResult(
                    step=step.step, tool=step.tool, ok=False,
                    duration_ms=int(STEP_TIMEOUT_SECONDS * 1000),
                    error=f"หมดเวลา ({STEP_TIMEOUT_SECONDS} วินาที)",
                )
            except Exception as exc:  # noqa: BLE001
                return StepResult(step=step.step, tool=step.tool, ok=False,
                                  duration_ms=int((time.time() - started) * 1000),
                                  error=f"{type(exc).__name__}: {exc}")

        for step in runnable:
            yield EventType.STEP_STARTED, {
                "step": step.step, "tool": step.tool, "purpose": step.purpose,
                "arguments": step.arguments, "depends_on": step.depends_on,
            }

        completed = await asyncio.gather(*(run_one(step) for step in runnable))
        for result in completed:
            results[result.step] = result
            pending.pop(result.step, None)
            yield EventType.STEP_RESULT, result.model_dump()
