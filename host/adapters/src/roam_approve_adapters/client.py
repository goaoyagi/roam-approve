"""Minimal stdlib-only HTTP client for the Bridge REST API."""

import json
import sys
import time
import urllib.error
import urllib.request

from .base import ApprovalRequest, Result

_VALID_STATUSES: frozenset[str] = frozenset(
    {"approved", "rejected", "expired", "pending"}
)


def _diag(message: str) -> None:
    print(f"roam-approve-hook: {message}", file=sys.stderr)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the Authorization header is never re-sent."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class BridgeClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base = base_url.rstrip("/")
        self._token = token

    def _request(
        self, method: str, path: str, body: dict | None, timeout: float
    ) -> dict | None:
        url = f"{self._base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as error:
            _diag(f"bridge returned HTTP {error.code}")
            return None
        except (urllib.error.URLError, OSError, TimeoutError):
            _diag("bridge unreachable")
            return None
        except (json.JSONDecodeError, UnicodeDecodeError):
            _diag("bridge returned malformed response")
            return None
        if not isinstance(payload, dict):
            _diag("bridge returned malformed response")
            return None
        return payload

    def create(self, request: ApprovalRequest, timeout_s: int) -> str | None:
        payload = self._request(
            "POST", "/v1/requests", request.to_payload(timeout_s), timeout=5
        )
        if payload is None:
            return None
        request_id = payload.get("id")
        if not isinstance(request_id, str) or not request_id:
            _diag("bridge returned malformed response")
            return None
        return request_id

    def wait(self, request_id: str, wait_s: float) -> Result:
        deadline = time.monotonic() + wait_s
        calls = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 and calls > 0:
                return "pending"
            chunk = min(max(remaining, 0.1), 300)
            calls += 1
            payload = self._request(
                "GET",
                f"/v1/requests/{request_id}/wait?timeout_s={chunk}",
                None,
                timeout=chunk + 5,
            )
            if payload is None:
                return "unreachable"
            status = payload.get("status")
            if status not in _VALID_STATUSES:
                _diag("bridge returned malformed response")
                return "unreachable"
            if status != "pending":
                return status  # type: ignore[return-value]
