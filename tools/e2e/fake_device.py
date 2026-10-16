#!/usr/bin/env python3
"""Fake M5StickC device for local simulation and e2e tests.

MQTT is treated only as a wake-up signal. Display/decision targets come
exclusively from device-token HTTP `GET /v1/requests?status=pending`.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Literal

import paho.mqtt.client as mqtt

REQUEST_TOPIC_FILTER = "roam/approval/request/+"
RESOLVED_TOPIC = "roam/approval/resolved"
DecisionMode = Literal["approve", "reject", "interactive"]


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise SystemExit(f"{name} is required")
    return value


class BridgeHttp:
    def __init__(self, base_url: str, token: str) -> None:
        self._base = base_url.rstrip("/")
        self._token = token

    def _request(
        self, method: str, path: str, body: dict | None = None
    ) -> tuple[int, object]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self._base}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode()
                payload = json.loads(raw) if raw else None
                return resp.status, payload
        except urllib.error.HTTPError as error:
            raw = error.read().decode()
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw
            return error.code, payload

    def list_pending(self) -> list[dict]:
        status, payload = self._request("GET", "/v1/requests?status=pending")
        if status != 200 or not isinstance(payload, list):
            print(f"fake-device: list pending failed: HTTP {status}", file=sys.stderr)
            return []
        return [item for item in payload if isinstance(item, dict)]

    def decide(self, request_id: str, decision: Literal["approve", "reject"]) -> bool:
        status, _payload = self._request(
            "POST",
            f"/v1/requests/{request_id}/decision",
            {"decision": decision, "source": "fake-device"},
        )
        if status != 200:
            print(
                f"fake-device: decision {decision} for {request_id} failed: HTTP {status}",
                file=sys.stderr,
            )
            return False
        return True


class FakeDevice:
    def __init__(
        self,
        *,
        bridge: BridgeHttp,
        mqtt_host: str,
        mqtt_port: int,
        mode: DecisionMode,
    ) -> None:
        self._bridge = bridge
        self._mode = mode
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._mqtt_host = mqtt_host
        self._mqtt_port = mqtt_port

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        client.subscribe(REQUEST_TOPIC_FILTER, qos=1)
        client.subscribe(RESOLVED_TOPIC, qos=1)
        self._wake.set()

    def _on_message(self, client, userdata, message) -> None:
        # Payload content is intentionally ignored; MQTT is a wake-up only.
        self._wake.set()

    def start(self) -> None:
        self._client.connect_async(self._mqtt_host, self._mqtt_port)
        self._client.loop_start()
        self.sync()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        self._client.loop_stop()
        self._client.disconnect()

    def sync(self) -> None:
        pending = self._bridge.list_pending()
        with self._lock:
            self._pending = {
                str(item["id"]): item for item in pending if "id" in item
            }
        self._render()

    def _render(self) -> None:
        with self._lock:
            items = list(self._pending.values())
        if not items:
            print("fake-device: idle (no pending requests)", flush=True)
            return
        for item in items:
            lines = item.get("lines") or []
            print(
                f"fake-device: pending id={item.get('id')} "
                f"agent={item.get('agent')} title={item.get('title')!r} "
                f"lines={lines!r}",
                flush=True,
            )
        if self._mode == "interactive":
            print("fake-device: press a=approve, r=reject, q=quit", flush=True)

    def _auto_decide(self) -> None:
        if self._mode == "interactive":
            return
        with self._lock:
            ids = list(self._pending)
        for request_id in ids:
            if self._bridge.decide(request_id, self._mode):
                print(
                    f"fake-device: auto-{self._mode} {request_id}",
                    flush=True,
                )
        self.sync()

    def _interactive_once(self) -> bool:
        """Handle one keypress. Returns False when the device should stop."""
        if not sys.stdin.isatty():
            time.sleep(0.2)
            return True
        ready, _, _ = select.select([sys.stdin], [], [], 0.2)
        if not ready:
            return True
        key = sys.stdin.read(1).lower()
        if key == "q":
            return False
        if key not in {"a", "r"}:
            return True
        decision: Literal["approve", "reject"] = "approve" if key == "a" else "reject"
        with self._lock:
            ids = list(self._pending)
        if not ids:
            print("fake-device: nothing pending", flush=True)
            return True
        # Decide the oldest pending request (sorted by created_at from Bridge).
        request_id = ids[0]
        if self._bridge.decide(request_id, decision):
            print(f"fake-device: {decision} {request_id}", flush=True)
        self.sync()
        return True

    def run(self) -> None:
        self.start()
        try:
            while not self._stop.is_set():
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                if self._stop.is_set():
                    break
                self.sync()
                if self._mode == "interactive":
                    if not self._interactive_once():
                        break
                else:
                    self._auto_decide()
        finally:
            self.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fake roam-approve device")
    parser.add_argument(
        "--auto",
        choices=("approve", "reject"),
        help="Automatically approve or reject pending requests",
    )
    args = parser.parse_args(argv)

    bridge_url = os.environ.get("ROAM_BRIDGE_URL", "http://127.0.0.1:8000")
    device_token = _env("ROAM_DEVICE_TOKEN")
    mqtt_host = os.environ.get("ROAM_MQTT_HOST", "127.0.0.1")
    mqtt_port = int(os.environ.get("ROAM_MQTT_PORT", "1883"))
    mode: DecisionMode = args.auto if args.auto else "interactive"

    device = FakeDevice(
        bridge=BridgeHttp(bridge_url, device_token),
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        mode=mode,
    )
    print(
        f"fake-device: bridge={bridge_url} mqtt={mqtt_host}:{mqtt_port} mode={mode}",
        flush=True,
    )
    device.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
