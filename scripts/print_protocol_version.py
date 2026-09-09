#!/usr/bin/env python3
"""Print the MCP protocol version the installed SDK implements.

Documentation that hardcodes a version number goes stale the moment the SDK
updates. Instructions reference the output of this script instead, so the
workshop always describes the version participants are actually running.
"""

from __future__ import annotations


def main() -> None:
    try:
        import mcp
        from mcp.types import LATEST_PROTOCOL_VERSION
    except ImportError:
        print("The `mcp` package is not installed. Run: make install")
        return

    print()
    print(f"  MCP Python SDK version : {getattr(mcp, '__version__', 'unknown')}")
    print(f"  Protocol revision      : {LATEST_PROTOCOL_VERSION}")
    print()
    print("  MCP versions are dates, not release numbers. Notable changes:")
    print("    2025-03-26  Streamable HTTP replaces HTTP+SSE; tool annotations; OAuth 2.1")
    print("    2025-06-18  Structured tool output; elicitation; JSON-RPC batching removed")
    print()
    print("  If sample code you find online uses two endpoints for SSE,")
    print("  it predates the transport change. Use streamable-http.")
    print()


if __name__ == "__main__":
    main()
