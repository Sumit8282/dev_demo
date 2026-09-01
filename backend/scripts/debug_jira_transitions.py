"""Debug Jira transitions for an issue."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.mcp.jira_mcp import JiraMCPClient, find_transition_id_for_status


async def main(issue_key: str = "SCRUM-6") -> None:
    settings = get_settings()
    async with JiraMCPClient(settings) as client:
        issue = await client.get_issue(issue_key)
        fields = issue.get("fields") if isinstance(issue, dict) else None
        status = fields.get("status") if isinstance(fields, dict) else issue.get("status")
        print("Current status:", json.dumps(status, indent=2))

        transitions = await client.get_transitions(issue_key)
        print(f"Transitions count: {len(transitions)}")
        for transition in transitions:
            to_status = transition.get("to") if isinstance(transition.get("to"), dict) else {}
            print(
                f"  id={transition.get('id')} "
                f"name={transition.get('name')} "
                f"to={(to_status or {}).get('name')}"
            )

        for target in ["Release", "Released", "Resolved", "Done", "In Progress"]:
            transition_id = find_transition_id_for_status(transitions, target)
            print(f"Match for {target!r}: {transition_id}")


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "SCRUM-6"
    asyncio.run(main(key))
