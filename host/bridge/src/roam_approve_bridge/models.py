#!/usr/bin/env python3
"""Bridge request and response models."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field, field_validator

Status = Literal["pending", "approved", "rejected", "expired"]
RequestLine = Annotated[str, Field(max_length=256)]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


class ApprovalRequestCreate(BaseModel):
    agent: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    lines: list[RequestLine] = Field(default_factory=list, max_length=32)
    timeout_s: int = Field(default=300, gt=0, le=3600)


class ApprovalRequest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    agent: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    lines: list[RequestLine] = Field(max_length=32)
    timeout_s: int = Field(gt=0, le=3600)
    created_at: datetime = Field(default_factory=utc_now)
    status: Status = "pending"
    decided_by: str | None = None

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _as_utc(value)

    @computed_field
    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=self.timeout_s)


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    source: str = Field(default="device", max_length=64)


class CreateResponse(BaseModel):
    id: UUID


class WaitResponse(BaseModel):
    status: Status
    reason: str | None = None
