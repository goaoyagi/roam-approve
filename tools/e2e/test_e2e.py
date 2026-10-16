"""End-to-end: hook → Bridge → MQTT → fake device → hook stdout."""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx
import paho.mqtt.client as mqtt
import pytest

_E2E_DIR = Path(__file__).resolve().parent
if str(_E2E_DIR) not in sys.path:
    sys.path.insert(0, str(_E2E_DIR))

from helpers import run_hook, sample_event, start_fake_device

pytestmark = pytest.mark.e2e


def test_hook_approve_via_fake_device(e2e_stack):
    device = start_fake_device(e2e_stack, auto="approve")
    try:
        time.sleep(1.0)
        result = run_hook(e2e_stack, sample_event("echo approve-me"), wait_s=30)
        assert result.returncode == 0, result.stderr.decode()
        assert result.stdout == b'{"decision":"approve"}\n'
    finally:
        device.stop()


def test_hook_reject_via_fake_device(e2e_stack):
    device = start_fake_device(e2e_stack, auto="reject")
    try:
        time.sleep(1.0)
        result = run_hook(e2e_stack, sample_event("echo reject-me"), wait_s=30)
        assert result.returncode == 0, result.stderr.decode()
        assert result.stdout == (
            b'{"decision":"block","reason":"Rejected on M5StickC"}\n'
        )
    finally:
        device.stop()


def test_hook_timeout_produces_no_stdout(e2e_stack):
    # No fake device: wait until ROAM_WAIT_S elapses, then fall back silently.
    result = run_hook(e2e_stack, sample_event("echo timeout-me"), wait_s=2, timeout=30)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""


def test_fake_mqtt_payload_is_not_approved(e2e_stack):
    """MQTT payload alone must not cause a decision (HTTP pending list wins)."""
    device = start_fake_device(e2e_stack, auto="approve")
    try:
        time.sleep(1.0)
        fake_id = str(uuid.uuid4())
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        client.connect(e2e_stack.mqtt_host, e2e_stack.mqtt_port)
        client.loop_start()
        try:
            payload = json.dumps(
                {
                    "id": fake_id,
                    "agent": "attacker",
                    "title": "fake",
                    "lines": ["rm -rf /"],
                    "expires_at": "2099-01-01T00:00:00+00:00",
                }
            )
            info = client.publish(
                f"roam/approval/request/{fake_id}",
                payload,
                qos=1,
                retain=True,
            )
            info.wait_for_publish(timeout=5)
            # Give the fake device time to wake and sync over HTTP.
            time.sleep(2.0)
            response = httpx.get(
                f"{e2e_stack.bridge_url}/v1/requests?status=pending",
                headers={"Authorization": f"Bearer {e2e_stack.device_token}"},
                timeout=5.0,
            )
            assert response.status_code == 200
            pending_ids = {item["id"] for item in response.json()}
            assert fake_id not in pending_ids

            # A real hook request must still be approved from HTTP state.
            result = run_hook(e2e_stack, sample_event("echo real-after-fake"), wait_s=30)
            assert result.returncode == 0, result.stderr.decode()
            assert result.stdout == b'{"decision":"approve"}\n'
        finally:
            client.publish(f"roam/approval/request/{fake_id}", b"", qos=1, retain=True)
            client.loop_stop()
            client.disconnect()
    finally:
        device.stop()
