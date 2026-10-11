#!/usr/bin/env python3
"""Bridge REST API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .auth import require_agent, require_device
from .models import (
    ApprovalRequest,
    ApprovalRequestCreate,
    CreateResponse,
    Decision,
    Status,
    WaitResponse,
)
from .store import AlreadyResolvedError, NotFoundError

router = APIRouter()


@router.post(
    "/v1/requests",
    status_code=201,
    response_model=CreateResponse,
    dependencies=[Depends(require_agent)],
)
async def create_request(
    payload: ApprovalRequestCreate,
    request: Request,
) -> CreateResponse:
    approval = request.app.state.store.add(payload)
    request.app.state.notifier.publish_request(approval)
    return CreateResponse(id=approval.id)


@router.get(
    "/v1/requests/{request_id}/wait",
    response_model=WaitResponse,
    dependencies=[Depends(require_agent)],
)
async def wait_request(
    request_id: UUID,
    request: Request,
    timeout_s: Annotated[float, Query(ge=0, le=300)] = 30,
) -> WaitResponse:
    try:
        approval = await request.app.state.store.wait(request_id, timeout_s)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail="request not found") from error

    reason = None
    if approval.status == "rejected":
        reason = f"rejected by {approval.decided_by}"
    elif approval.status == "expired":
        reason = "expired before decision"
    return WaitResponse(status=approval.status, reason=reason)


@router.post(
    "/v1/requests/{request_id}/decision",
    response_model=ApprovalRequest,
    dependencies=[Depends(require_device)],
)
async def decide_request(
    request_id: UUID,
    decision: Decision,
    request: Request,
) -> ApprovalRequest:
    try:
        return request.app.state.store.decide(request_id, decision)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail="request not found") from error
    except AlreadyResolvedError as error:
        raise HTTPException(status_code=409, detail="request already resolved") from error


@router.get(
    "/v1/requests",
    response_model=list[ApprovalRequest],
    dependencies=[Depends(require_device)],
)
async def list_requests(
    request: Request,
    status: Status | None = None,
) -> list[ApprovalRequest]:
    return request.app.state.store.list(status)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
