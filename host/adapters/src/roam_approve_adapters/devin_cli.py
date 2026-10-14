"""Adapter for Devin CLI/Desktop PermissionRequest hooks."""

import json

from .base import AgentAdapter, ApprovalRequest, Result


def summarize(text: str, width: int = 20, max_lines: int = 6) -> list[str]:
    lines: list[str] = []
    for raw in text.split("\n"):
        line = raw.rstrip("\r").replace("\t", " ")
        if not line:
            continue
        for start in range(0, len(line), width):
            lines.append(line[start : start + width])
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        lines[-1] = last[: width - 1] + "…"
    return lines


class DevinCliAdapter(AgentAdapter):
    name = "devin-cli"

    def parse(self, event: dict) -> ApprovalRequest | None:
        if not isinstance(event, dict):
            return None
        tool_name = event.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            return None
        session_id = event.get("session_id")
        session = str(session_id)[:128] if session_id else "unknown"
        tool_input = event.get("tool_input")
        source = ""
        if isinstance(tool_input, dict):
            for key in ("command", "file_path"):
                value = tool_input.get(key)
                if isinstance(value, str) and value:
                    source = value
                    break
        return ApprovalRequest(
            agent=self.name,
            session_id=session,
            title=tool_name[:256],
            lines=summarize(source) if source else [],
        )

    def render(self, result: Result) -> tuple[str, int]:
        if result == "approved":
            return json.dumps({"decision": "approve"}, separators=(",", ":")), 0
        if result == "rejected":
            return (
                json.dumps(
                    {"decision": "block", "reason": "Rejected on M5StickC"},
                    separators=(",", ":"),
                ),
                0,
            )
        return "", 0
