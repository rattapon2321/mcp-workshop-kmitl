"""MCP server surface and behaviour.

Checks the contract the whole system depends on: the tools exist, they declare
annotations honestly, and they refuse what they should refuse.
"""

from __future__ import annotations

import pytest
from conftest import needs_neo4j, needs_opensearch, needs_postgres


@pytest.fixture(scope="module")
def server():
    import server as mcp_server

    return mcp_server.build_server()


class TestSurface:
    async def test_tools_are_registered(self, server):
        tools = await server.list_tools()
        names = {t.name for t in tools}
        for required in ("search_tickets", "get_device_config", "get_device_neighbors",
                         "get_upstream_devices", "search_logs", "count_log_events",
                         "calculate_health_score", "run_report_script"):
            assert required in names, f"missing tool: {required}"

    async def test_every_tool_has_a_description(self, server):
        for tool in await server.list_tools():
            assert tool.description and len(tool.description) > 40, (
                f"{tool.name} needs a real description - it is the only thing "
                f"the model uses to choose"
            )

    async def test_read_tools_declare_read_only(self, server):
        """An honest readOnlyHint is what lets a client skip a permission prompt."""
        writes = {"generate_report"}
        for tool in await server.list_tools():
            annotations = getattr(tool, "annotations", None)
            if annotations is None:
                pytest.fail(f"{tool.name} has no annotations")
            read_only = getattr(annotations, "readOnlyHint", None)
            if tool.name in writes:
                assert read_only is False
            else:
                assert read_only is True, f"{tool.name} should declare readOnlyHint"

    async def test_no_tool_touches_the_outside_world(self, server):
        """openWorldHint false everywhere: nothing leaves the organisation."""
        for tool in await server.list_tools():
            annotations = getattr(tool, "annotations", None)
            assert getattr(annotations, "openWorldHint", None) is False

    async def test_resources_are_registered(self, server):
        uris = {str(r.uri) for r in await server.list_resources()}
        assert any("schema://" in u for u in uris)
        assert any("clock://" in u for u in uris)


@needs_postgres
class TestTicketTools:
    async def test_search_tickets_returns_data(self, server):
        result = await server.call_tool("search_tickets", {"status": "open"})
        assert result is not None

    async def test_unknown_device_is_reported_not_invented(self, server):
        """The single most important behaviour in the whole system."""
        result = await server.call_tool("get_device_config", {"device_id": "PE-CNX-99"})
        text = str(result)
        assert "ไม่พบ" in text or "found" in text.lower()
        assert "available_devices" in text, (
            "when something does not exist, say what does"
        )


@needs_neo4j
class TestNetworkTools:
    async def test_shared_upstream_is_found(self, server):
        """Scenario S1 hinges on this returning APE-NBI-03."""
        result = await server.call_tool(
            "get_upstream_devices",
            {"device_ids": ["LPE-NBI-11", "LPE-NBI-12", "LPE-NBI-13"]},
        )
        assert "APE-NBI-03" in str(result)


@needs_opensearch
class TestLogTools:
    async def test_relative_range_is_required(self, server):
        """Absolute dates are refused on purpose: models get dates wrong."""
        result = await server.call_tool(
            "search_logs", {"range": "2025-08-01", "device_id": "APE-NBI-03"}
        )
        assert "range" in str(result).lower() or "error" in str(result).lower()

    async def test_results_are_capped(self, server):
        result = await server.call_tool(
            "search_logs", {"range": "last_30d", "limit": 99999}
        )
        text = str(result)
        assert "truncated" in text or "returned" in text


class TestScriptSandbox:
    @pytest.mark.parametrize("name", [
        "../../etc/passwd",
        "rm -rf /",
        "open_tickets_summary; cat /etc/passwd",
        "unknown_script",
    ])
    async def test_unlisted_script_never_runs(self, server, name):
        """The requirement is that it does not execute.

        A refusal may surface either as a raised ToolError or as an error
        result depending on the SDK version, so accept both shapes - what must
        never happen is a successful run.
        """
        try:
            result = await server.call_tool("run_report_script", {"name": name})
        except Exception as exc:  # noqa: BLE001 - refusal by exception is fine
            assert "อนุญาต" in str(exc) or "ปฏิเสธ" in str(exc)
            return
        text = str(result)
        assert "ปฏิเสธ" in text or "error" in text.lower(), (
            f"run_report_script appears to have accepted {name!r}"
        )
