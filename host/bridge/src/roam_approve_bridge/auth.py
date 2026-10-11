#!/usr/bin/env python3
"""Bearer token dependencies for bridge endpoints."""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def _require_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    token_name: str,
) -> None:
    settings = request.app.state.settings
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    expected = getattr(settings, token_name).get_secret_value()
    if not secrets.compare_digest(
        credentials.credentials.encode(),
        expected.encode(),
    ):
        raise HTTPException(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_agent(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    _require_token(request, credentials, "agent_token")


async def require_device(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    _require_token(request, credentials, "device_token")
