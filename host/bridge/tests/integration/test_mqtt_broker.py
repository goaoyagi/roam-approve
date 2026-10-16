"""Integration tests against a live mosquitto broker."""

from __future__ import annotations

import json
import subprocess
import time

import httpx
import pytest

from .helpers import (
    REPO_ROOT,
    create_request,
    decide_request,
    fetch_retained,
    mosquitto_identity,
    start_bridge,
)

pytestmark = pytest.mark.integration


def test_create_delivers_retained_request(bridge, observer):
    observer.clear()
    request_id = create_request(bridge, title="retained-check")
    # Wait for the always-on observer first (may be live or retained).
    observer.wait_for_request(request_id)
    retained = fetch_retained(request_id)
    assert retained is not None and retained != b""
    payload = json.loads(retained.decode())
    assert payload["id"] == request_id
    assert payload["title"] == "retained-check"
    assert payload["agent"] == "devin-cli"
    assert "make test" in payload["lines"]


def test_resolving_one_request_keeps_other_retained(bridge, observer):
    observer.clear()
    first = create_request(bridge, title="keep-me")
    second = create_request(bridge, title="resolve-me")
    observer.wait_for_request(first)
    observer.wait_for_request(second)

    decide_request(bridge, second, "reject")
    observer.wait_for_clear(second)
    observer.wait_for_resolved(second, "rejected")

    retained_first = fetch_retained(first)
    assert retained_first is not None and retained_first != b""
    assert json.loads(retained_first.decode())["id"] == first

    retained_second = fetch_retained(second)
    assert retained_second in (None, b"")


def test_resolve_and_expire_clear_retained_and_publish_resolved(bridge, observer):
    observer.clear()
    approved_id = create_request(bridge, title="to-approve")
    observer.wait_for_request(approved_id)
    decide_request(bridge, approved_id, "approve")
    observer.wait_for_clear(approved_id)
    observer.wait_for_resolved(approved_id, "approved")
    assert fetch_retained(approved_id) in (None, b"")

    # Short-lived request: do not call HTTP after create so only the sweeper
    # can expire it (store.get/list/wait/decide also expire-on-read).
    observer.clear()
    expired_id = create_request(bridge, title="to-expire", timeout_s=1)
    observer.wait_for_request(expired_id)
    observer.wait_for_clear(expired_id, timeout=10.0)
    observer.wait_for_resolved(expired_id, "expired", timeout=10.0)
    assert fetch_retained(expired_id) in (None, b"")


def test_bridge_restart_clears_stale_retained(bridge, observer):
    identity_before = mosquitto_identity()
    observer.clear()
    request_id = create_request(bridge, title="stale-after-restart")
    observer.wait_for_request(request_id)
    assert fetch_retained(request_id) not in (None, b"")

    port = bridge.port
    bridge.stop()
    # Retained must still be present while only Bridge is down.
    assert fetch_retained(request_id) not in (None, b"")

    restarted = start_bridge(port=port)
    try:
        observer.wait_for(
            lambda m: m.topic.endswith(request_id) and m.payload == b"",
            timeout=10.0,
            description="stale retained clear after restart",
        )
        assert fetch_retained(request_id) in (None, b"")
    finally:
        restarted.stop()

    identity_after = mosquitto_identity()
    if identity_before is not None and identity_after is not None:
        assert identity_before == identity_after, (
            "mosquitto container was restarted; restart test is invalid"
        )


def test_bridge_starts_without_broker_and_reconnects(require_broker, observer):
    identity_before = mosquitto_identity()
    if identity_before is None:
        pytest.skip("docker compose mosquitto identity unavailable")

    subprocess.check_call(
        ["docker", "compose", "stop", "mosquitto"],
        cwd=REPO_ROOT,
    )
    bridge = None
    try:
        bridge = start_bridge()
        response = httpx.get(f"{bridge.base_url}/healthz", timeout=2.0)
        assert response.status_code == 200

        subprocess.check_call(
            ["docker", "compose", "start", "mosquitto"],
            cwd=REPO_ROOT,
        )
        # paho reconnects asynchronously; wait until publish is observed.
        deadline = time.monotonic() + 20.0
        last_error: Exception | None = None
        request_id = None
        while time.monotonic() < deadline:
            try:
                observer.clear()
                request_id = create_request(bridge, title="after-reconnect")
                observer.wait_for_request(request_id, timeout=3.0)
                break
            except Exception as error:  # noqa: BLE001 - retry until MQTT reconnects
                last_error = error
                time.sleep(0.5)
        assert request_id is not None, f"MQTT did not recover: {last_error}"
        assert fetch_retained(request_id) not in (None, b"")
    finally:
        if bridge is not None:
            bridge.stop()
        subprocess.check_call(
            ["docker", "compose", "start", "mosquitto"],
            cwd=REPO_ROOT,
        )
        identity_after = mosquitto_identity()
        if identity_after is not None:
            assert identity_before[0] == identity_after[0]
