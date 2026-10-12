"""Shared types for agent adapters."""

from dataclasses import dataclass, field
from typing import Literal, Protocol

Result = Literal["approved", "rejected", "expired", "pending", "unreachable"]


@dataclass(frozen=True)
class ApprovalRequest:
    agent: str
    session_id: str
    title: str
    lines: list[str] = field(default_factory=list)

    def to_payload(self, timeout_s: int) -> dict:
        return {
            "agent": self.agent,
            "session_id": self.session_id,
            "title": self.title,
            "lines": self.lines,
            "timeout_s": timeout_s,
        }


class AgentAdapter(Protocol):
    name: str

    def parse(self, event: dict) -> ApprovalRequest | None:
        """Convert a raw hook event into an ApprovalRequest.

        Returns None when the event is not applicable (no output, exit 0).
        """
        ...

    def render(self, result: Result) -> tuple[str, int]:
        """Return (stdout text, exit code) for a final result."""
        ...
