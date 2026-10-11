#!/usr/bin/env python3
"""In-memory approval request store."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from .models import ApprovalRequest, ApprovalRequestCreate, Decision, Status, utc_now

logger = logging.getLogger(__name__)


class NotFoundError(Exception):
    """Raised when an approval request does not exist."""


class AlreadyResolvedError(Exception):
    """Raised when an approval request is no longer pending."""


class ApprovalStore:
    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        on_resolved: Callable[[ApprovalRequest], None] | None = None,
    ) -> None:
        self._clock = clock
        self._on_resolved = on_resolved
        self._requests: dict[UUID, ApprovalRequest] = {}
        self._events: dict[UUID, asyncio.Event] = {}

    def add(self, create: ApprovalRequestCreate) -> ApprovalRequest:
        request = ApprovalRequest(
            agent=create.agent,
            session_id=create.session_id,
            title=create.title,
            lines=create.lines,
            timeout_s=create.timeout_s,
            created_at=self._clock(),
        )
        self._requests[request.id] = request
        self._events[request.id] = asyncio.Event()
        return request

    def get(self, request_id: UUID) -> ApprovalRequest:
        request = self._get_known(request_id)
        self._expire_if_due(request, self._clock())
        return request

    def list(self, status: Status | None = None) -> list[ApprovalRequest]:
        now = self._clock()
        for request in self._requests.values():
            self._expire_if_due(request, now)
        requests = self._requests.values()
        if status is not None:
            requests = (request for request in requests if request.status == status)
        return sorted(requests, key=lambda request: request.created_at)

    def decide(self, request_id: UUID, decision: Decision) -> ApprovalRequest:
        request = self.get(request_id)
        if request.status != "pending":
            raise AlreadyResolvedError(request_id)
        status: Status = "approved" if decision.decision == "approve" else "rejected"
        self._resolve(request, status, decision.source)
        return request

    async def wait(self, request_id: UUID, timeout_s: float) -> ApprovalRequest:
        request = self.get(request_id)
        if request.status != "pending":
            return request

        seconds_until_expiry = (request.expires_at - self._clock()).total_seconds()
        if seconds_until_expiry <= 0:
            self._expire_if_due(request, self._clock())
            return request

        event = self._events[request_id]
        try:
            await asyncio.wait_for(event.wait(), min(timeout_s, seconds_until_expiry))
        except TimeoutError:
            pass
        return self.get(request_id)

    def expire_due(self) -> int:
        now = self._clock()
        expired = 0
        for request in self._requests.values():
            if (
                request.status == "pending"
                and now >= request.expires_at
                and self._resolve(request, "expired", None)
            ):
                expired += 1
        return expired

    def _get_known(self, request_id: UUID) -> ApprovalRequest:
        try:
            return self._requests[request_id]
        except KeyError as error:
            raise NotFoundError(request_id) from error

    def _expire_if_due(self, request: ApprovalRequest, now: datetime) -> None:
        if request.status == "pending" and now >= request.expires_at:
            self._resolve(request, "expired", None)

    def _resolve(
        self,
        request: ApprovalRequest,
        status: Status,
        decided_by: str | None,
    ) -> bool:
        if request.status != "pending":
            return False
        request.status = status
        request.decided_by = decided_by
        self._events[request.id].set()
        if self._on_resolved is not None:
            try:
                self._on_resolved(request)
            except Exception:
                logger.warning("approval resolution callback failed", exc_info=True)
        return True
