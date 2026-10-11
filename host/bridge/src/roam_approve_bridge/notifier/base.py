#!/usr/bin/env python3
"""Notifier protocol and MQTT message payloads."""

from datetime import UTC
from typing import Protocol

from ..models import ApprovalRequest

REQUEST_TOPIC = "roam/approval/request"
RESOLVED_TOPIC = "roam/approval/resolved"


def request_payload(request: ApprovalRequest) -> dict[str, object]:
    return {
        "id": str(request.id),
        "agent": request.agent,
        "title": request.title,
        "lines": request.lines,
        "expires_at": request.expires_at.astimezone(UTC).isoformat(),
    }


def resolved_payload(request: ApprovalRequest) -> dict[str, str]:
    return {"id": str(request.id), "status": request.status}


class Notifier(Protocol):
    def start(self) -> None: ...

    def close(self) -> None: ...

    def publish_request(self, request: ApprovalRequest) -> None: ...

    def publish_resolved(self, request: ApprovalRequest) -> None: ...
