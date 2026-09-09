"""Loop protection.

Runs without any service: the guard is pure logic, which is exactly why it can
be relied on. Module 6 argues that one stop condition is never enough - these
tests pin down all three.
"""

from __future__ import annotations

import pytest
from agent.executor import LoopGuard, resolve_reference
from schemas import StepResult


class TestLoopGuard:
    def test_allows_normal_sequence(self):
        guard = LoopGuard()
        assert guard.check("search_tickets", {"status": "open"}) is None
        assert guard.check("get_upstream_devices", {"device_ids": ["a"]}) is None
        assert guard.check("search_logs", {"device_id": "x"}) is None

    def test_blocks_identical_repeat(self):
        """The tight retry loop: same tool, same arguments, forever."""
        guard = LoopGuard()
        assert guard.check("search_tickets", {"status": "open"}) is None
        reason = guard.check("search_tickets", {"status": "open"})
        assert reason is not None and "ซ้ำ" in reason

    def test_blocks_argument_fuzzing(self):
        """Different arguments each time still counts as a loop."""
        guard = LoopGuard()
        blocked = None
        for i in range(10):
            blocked = guard.check("search_logs", {"limit": i})
            if blocked:
                break
        assert blocked is not None

    def test_blocks_total_step_budget(self, monkeypatch):
        import agent.executor as executor

        monkeypatch.setattr(executor, "MAX_STEPS", 3)
        monkeypatch.setattr(executor, "MAX_SAME_TOOL_CALLS", 99)
        guard = executor.LoopGuard()
        results = [guard.check(f"tool_{i}", {"i": i}) for i in range(5)]
        assert results[-1] is not None


class TestResolveReference:
    def _results(self):
        return {
            1: StepResult(step=1, tool="search_tickets", ok=True, duration_ms=1,
                          result={"tickets": [{"device_id": "LPE-NBI-11"},
                                              {"device_id": "LPE-NBI-12"}]}),
            2: StepResult(step=2, tool="get_upstream_devices", ok=False,
                          duration_ms=1, error="boom"),
        }

    def test_simple_path(self):
        assert resolve_reference("step.1.tickets.0.device_id", self._results()) == "LPE-NBI-11"

    def test_wildcard_collects_every_element(self):
        """This is what turns 'the tickets from step 1' into a device list."""
        assert resolve_reference("step.1.tickets.*.device_id", self._results()) == [
            "LPE-NBI-11", "LPE-NBI-12"
        ]

    def test_failed_step_yields_none(self):
        assert resolve_reference("step.2.shared_by_all", self._results()) is None

    def test_missing_step_yields_none(self):
        assert resolve_reference("step.9.anything", self._results()) is None
