"""Tool selection accuracy - the measurement for challenge 3.

Run before and after editing descriptions:

    make test -- tests/test_tool_selection.py

The score is the point. A participant who improves 5/12 to 11/12 by editing
prose alone has learned something no lecture conveys as well.
"""

from __future__ import annotations

import pytest
from conftest import needs_llm

pytestmark = needs_llm

CHOOSER_PROMPT = """\
You choose exactly one tool to answer a question about an IP-MPLS network.
Reply with the tool name only, nothing else.

Available tools:
{catalogue}
"""


async def _choose(question: str, descriptions: dict) -> str:
    from agent import llm

    catalogue = "\n\n".join(f"{name}: {desc}" for name, desc in descriptions.items())
    reply = await llm.complete(
        [
            {"role": "system", "content": CHOOSER_PROMPT.format(catalogue=catalogue)},
            {"role": "user", "content": question},
        ],
        temperature=0.0, max_tokens=32,
    )
    return reply.strip().strip("`").split()[0] if reply.strip() else ""


async def test_tool_selection_accuracy(tool_cases, capsys):
    descriptions = tool_cases["descriptions_under_test"]
    cases = tool_cases["cases"]

    correct, wrong = 0, []
    for case in cases:
        chosen = await _choose(case["question"], descriptions)
        if chosen == case["expected_tool"]:
            correct += 1
        else:
            wrong.append((case["id"], case["question"], case["expected_tool"], chosen))

    with capsys.disabled():
        print(f"\n\n  Tool selection: {correct}/{len(cases)}")
        for cid, question, expected, got in wrong:
            print(f"    {cid}  {question[:44]}")
            print(f"          expected {expected}, got {got}")
        if correct < len(cases):
            print("\n  Improve the descriptions in "
                  "data/challenge_fixtures/tool_selection_cases.json")
            print("  Rules that help most: say when NOT to use the tool, and "
                  "which tool to use instead.\n")

    # The starting descriptions are deliberately bad, so the bar is the
    # challenge target rather than perfection.
    assert correct >= 10, (
        f"got {correct}/{len(cases)}; challenge 3 requires at least 10"
    )
