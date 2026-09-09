"""Events streamed from the agent to the UI.

The UI is not decoration here. A participant debugging their own agent needs
to see the intent decision, the plan, each tool call and each result as they
happen - and so does an audience watching a demo. Both are served by the same
event stream.

Event order for a normal in-scope question:

    intent_checked -> memory_updated -> plan_created
    -> step_started -> step_result   (repeated)
    -> grounding_checked -> token ... -> usage -> done
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any


class EventType(str, Enum):
    INTENT_CHECKED = "intent_checked"
    MEMORY_UPDATED = "memory_updated"
    TOPIC_CHANGED = "topic_changed"
    PLAN_CREATED = "plan_created"
    STEP_STARTED = "step_started"
    STEP_RESULT = "step_result"
    GROUNDING_CHECKED = "grounding_checked"
    TOKEN = "token"
    USAGE = "usage"
    ERROR = "error"
    DONE = "done"


def sse(event_type: EventType, data: Any) -> str:
    """Format one Server-Sent Event.

    The blank line at the end is required by the SSE spec; leaving it out
    produces a stream that appears to hang.
    """
    payload = json.dumps({"type": event_type.value, "data": data},
                         ensure_ascii=False, default=str)
    return f"event: {event_type.value}\ndata: {payload}\n\n"
