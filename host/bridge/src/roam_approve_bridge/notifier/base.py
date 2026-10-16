#!/usr/bin/env python3
"""Notifier protocol and MQTT message payloads."""

from datetime import UTC
from typing import Protocol
from uuid import UUID

from ..models import ApprovalRequest

REQUEST_TOPIC = "roam/approval/request"
REQUEST_TOPIC_FILTER = f"{REQUEST_TOPIC}/+"
RESOLVED_TOPIC = "roam/approval/resolved"

# Request payloads are only a summary (the device re-fetches over HTTP) and
# must stay well under the firmware's 4096-byte MQTT buffer, which silently
# drops larger messages.
PAYLOAD_TITLE_CHARS = 64
PAYLOAD_LINE_CHARS = 40
PAYLOAD_MAX_LINES = 6


def request_topic(request_id: UUID | str) -> str:
    return f"{REQUEST_TOPIC}/{request_id}"


def request_payload(request: ApprovalRequest) -> dict[str, object]:
    return {
        "id": str(request.id),
        "agent": request.agent,
        "title": request.title[:PAYLOAD_TITLE_CHARS],
        "lines": [
            line[:PAYLOAD_LINE_CHARS]
            for line in request.lines[:PAYLOAD_MAX_LINES]
        ],
        "expires_at": request.expires_at.astimezone(UTC).isoformat(),
    }


def resolved_payload(request: ApprovalRequest) -> dict[str, str]:
    return {"id": str(request.id), "status": request.status}


class Notifier(Protocol):
    def start(self) -> None: ...

    def close(self) -> None: ...

    def publish_request(self, request: ApprovalRequest) -> None: ...

    def publish_resolved(self, request: ApprovalRequest) -> None: ...
