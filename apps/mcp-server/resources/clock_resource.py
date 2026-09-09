"""Publish the system's notion of "now" as a Resource.

A model has no reliable idea what today's date is, and this dataset moves
every time it is re-seeded. Reading this resource before planning is what
stops an agent from confidently filtering on a window where no data exists.
"""

from __future__ import annotations

import json

import clock


def register(mcp) -> None:

    @mcp.resource("clock://now")
    def now() -> str:
        """Current time as this system defines it, plus the data coverage window.

        Read before answering any question that mentions time. "now" here is the
        newest record in the system, not the server clock.
        """
        return json.dumps(clock.coverage(), ensure_ascii=False, indent=2)
