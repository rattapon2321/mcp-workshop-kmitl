"""Client for the MCP server.

The agent never talks to PostgreSQL, Neo4j or OpenSearch directly. Everything
goes through MCP, which is what makes the same server usable from Claude
Desktop, Cursor and this API without a second implementation.

Two modes:
  in_process  - import the server and call its tools directly. Fast, and the
                default during labs so participants do not need two terminals.
  http        - talk to a running server over Streamable HTTP, which is what
                production looks like.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

MODE = os.getenv("MCP_CLIENT_MODE", "in_process")
SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:9000/mcp")

_MCP_SERVER_DIR = Path(__file__).resolve().parents[3] / "apps" / "mcp-server"


class MCPClient:
    def __init__(self) -> None:
        self._server = None
        self._tools_cache: list[dict] | None = None

    # ------------------------------------------------------------------

    def _ensure_server(self):
        if self._server is None:
            sys.path.insert(0, str(_MCP_SERVER_DIR))
            import server as mcp_server  # noqa: PLC0415

            self._server = mcp_server.build_server()
        return self._server

    async def list_tools(self) -> list[dict]:
        """Tool definitions, cached. The planner needs the names, the
        descriptions and the argument schemas to produce a runnable plan."""
        if self._tools_cache is not None:
            return self._tools_cache

        server = self._ensure_server()
        tools = await server.list_tools()
        self._tools_cache = [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
                "annotations": getattr(tool, "annotations", None),
            }
            for tool in tools
        ]
        return self._tools_cache

    async def list_resources(self) -> list[dict]:
        server = self._ensure_server()
        resources = await server.list_resources()
        return [
            {"uri": str(r.uri), "name": r.name, "description": r.description or ""}
            for r in resources
        ]

    async def read_resource(self, uri: str) -> str:
        server = self._ensure_server()
        contents = await server.read_resource(uri)
        parts = [getattr(c, "content", "") or getattr(c, "text", "") for c in contents]
        return "\n".join(str(p) for p in parts)

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Invoke a tool and return its result.

        Errors are returned as data rather than raised, so a failed step
        becomes something the agent can reason about and recover from instead
        of an exception that ends the turn.
        """
        server = self._ensure_server()
        try:
            result = await server.call_tool(name, arguments)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}

        # FastMCP returns (content_blocks, structured_result) on recent versions
        # and a bare list on older ones. Handle both.
        if isinstance(result, tuple) and len(result) == 2:
            _, structured = result
            if structured is not None:
                return structured
            result = result[0]

        if isinstance(result, list):
            texts = []
            for block in result:
                text = getattr(block, "text", None)
                if text is not None:
                    texts.append(text)
            if len(texts) == 1:
                import json

                try:
                    return json.loads(texts[0])
                except (ValueError, TypeError):
                    return texts[0]
            return texts
        return result


_CLIENT: MCPClient | None = None


def get() -> MCPClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = MCPClient()
    return _CLIENT
