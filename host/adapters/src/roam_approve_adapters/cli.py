"""roam-approve-hook entry point.

Hook safety rule: any failure must produce no stdout and exit 0 so the
agent falls back to its normal prompt. Never exit non-zero.
"""

import json
import os
import sys
import time

from .client import BridgeClient
from .registry import get_adapter

# hooks.v1.json gives the hook a 300s timeout; keep the wait plus ~20s of
# HTTP overhead below it.
MAX_WAIT_S = 280


def _diag(message: str) -> None:
    print(f"roam-approve-hook: {message}", file=sys.stderr)


def _wait_seconds() -> int:
    raw = os.environ.get("ROAM_WAIT_S", "")
    try:
        value = int(raw) if raw else 240
    except ValueError:
        value = 240
    return max(1, min(MAX_WAIT_S, value))


def _run(argv: list[str]) -> int:
    if not argv:
        _diag("missing agent name")
        return 0
    adapter = get_adapter(argv[0])
    if adapter is None:
        _diag(f"unknown agent: {argv[0]}")
        return 0

    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, UnicodeDecodeError):
        _diag("invalid stdin JSON")
        return 0

    request = adapter.parse(event)
    if request is None:
        return 0

    token = os.environ.get("ROAM_AGENT_TOKEN", "")
    if not token:
        _diag("ROAM_AGENT_TOKEN is not set")
        return 0

    bridge_url = os.environ.get("ROAM_BRIDGE_URL", "http://127.0.0.1:8000")
    wait_s = _wait_seconds()

    deadline = time.monotonic() + wait_s
    client = BridgeClient(bridge_url, token)
    request_id = client.create(request, timeout_s=wait_s)
    if request_id is None:
        return 0

    result = client.wait(request_id, deadline - time.monotonic())
    stdout_text, exit_code = adapter.render(result)
    if stdout_text:
        print(stdout_text)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        return _run(argv)
    except Exception:  # noqa: BLE001 - hooks must never propagate or exit non-zero
        _diag("unexpected error")
        return 0


def watch_main() -> None:
    print("roam-approve-watch: not implemented (see GitHub issues)", file=sys.stderr)
    sys.exit(1)
