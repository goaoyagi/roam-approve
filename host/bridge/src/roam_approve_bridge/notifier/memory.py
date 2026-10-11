#!/usr/bin/env python3
"""In-memory notifier for tests and local development."""

from dataclasses import dataclass

from ..models import ApprovalRequest
from .base import (
    REQUEST_TOPIC,
    RESOLVED_TOPIC,
    request_payload,
    resolved_payload,
)


@dataclass(frozen=True)
class PublishedMessage:
    topic: str
    payload: dict[str, object] | None
    retain: bool


class MemoryNotifier:
    def __init__(self) -> None:
        self.messages: list[PublishedMessage] = []

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def publish_request(self, request: ApprovalRequest) -> None:
        self.messages.append(
            PublishedMessage(REQUEST_TOPIC, request_payload(request), retain=True)
        )

    def publish_resolved(self, request: ApprovalRequest) -> None:
        self.messages.append(PublishedMessage(REQUEST_TOPIC, None, retain=True))
        self.messages.append(
            PublishedMessage(
                RESOLVED_TOPIC,
                resolved_payload(request),
                retain=False,
            )
        )
