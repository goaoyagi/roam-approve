"""Helpers for Bridge + real mosquitto integration tests."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import paho.mqtt.client as mqtt
from roam_approve_bridge.notifier.base import (
    REQUEST_TOPIC_FILTER,
    RESOLVED_TOPIC,
    request_topic,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENT_TOKEN = "test-token-agent-integration"
DEVICE_TOKEN = "test-token-device-integration"


def mqtt_reachable(host: str = "127.0.0.1", port: int = 1883, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@dataclass
class ObservedMessage:
    topic: str
    payload: bytes
    retain: bool


@dataclass
class MqttObserver:
    """Long-lived MQTT client that records messages for assertions."""

    host: str = "127.0.0.1"
    port: int = 1883
    messages: list[ObservedMessage] = field(default_factory=list)
    _client: mqtt.Client = field(init=False, repr=False)
    _connected: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        import threading

        self._connected = threading.Event()
        self._lock = threading.Lock()
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"observer-{uuid.uuid4()}",
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        client.subscribe(REQUEST_TOPIC_FILTER, qos=1)
        client.subscribe(RESOLVED_TOPIC, qos=1)
        self._connected.set()

    def _on_message(self, client, userdata, message) -> None:
        with self._lock:
            self.messages.append(
                ObservedMessage(
                    topic=message.topic,
                    payload=bytes(message.payload),
                    retain=bool(message.retain),
                )
            )

    def start(self) -> None:
        self._client.connect(self.host, self.port, keepalive=30)
        self._client.loop_start()
        if not self._connected.wait(timeout=5):
            raise RuntimeError("MQTT observer failed to connect")

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def clear(self) -> None:
        with self._lock:
            self.messages.clear()

    def wait_for(
        self,
        predicate,
        *,
        timeout: float = 10.0,
        description: str = "condition",
    ) -> ObservedMessage:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for message in self.messages:
                    if predicate(message):
                        return message
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {description}")

    def wait_for_request(self, request_id: str, *, timeout: float = 10.0) -> ObservedMessage:
        topic = request_topic(request_id)
        return self.wait_for(
            lambda m: m.topic == topic and bool(m.payload),
            timeout=timeout,
            description=f"request {request_id}",
        )

    def wait_for_clear(self, request_id: str, *, timeout: float = 10.0) -> ObservedMessage:
        topic = request_topic(request_id)
        self.wait_for_request(request_id, timeout=timeout)
        return self.wait_for(
            lambda m: m.topic == topic and m.payload == b"",
            timeout=timeout,
            description=f"clear of {request_id}",
        )

    def wait_for_resolved(
        self, request_id: str, status: str, *, timeout: float = 10.0
    ) -> ObservedMessage:
        def match(message: ObservedMessage) -> bool:
            if message.topic != RESOLVED_TOPIC or not message.payload:
                return False
            try:
                payload = json.loads(message.payload.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                return False
            return payload.get("id") == request_id and payload.get("status") == status

        return self.wait_for(
            match,
            timeout=timeout,
            description=f"resolved {request_id} status={status}",
        )


def fetch_retained(request_id: str, *, timeout: float = 5.0) -> bytes | None:
    """Connect fresh and return the retained payload for a request topic."""
    topic = request_topic(request_id)
    import threading

    got = threading.Event()
    holder: dict[str, bytes | None] = {"payload": None}
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"retain-{uuid.uuid4()}",
    )

    def on_connect(client, userdata, flags, reason_code, properties) -> None:
        client.subscribe(topic, qos=1)

    def on_message(client, userdata, message) -> None:
        if message.topic == topic and message.retain:
            holder["payload"] = bytes(message.payload)
            got.set()

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect("127.0.0.1", 1883, keepalive=30)
    client.loop_start()
    try:
        if not got.wait(timeout=timeout):
            return None
        return holder["payload"]
    finally:
        client.loop_stop()
        client.disconnect()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class BridgeProc:
    port: int
    process: subprocess.Popen[str]
    tmp_cwd: Path
    base_url: str

    def headers(self, role: str) -> dict[str, str]:
        token = AGENT_TOKEN if role == "agent" else DEVICE_TOKEN
        return {"Authorization": f"Bearer {token}"}

    def wait_healthy(self, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"{self.base_url}/healthz", timeout=1.0)
                if response.status_code == 200 and response.json().get("status") == "ok":
                    return
            except Exception as error:  # noqa: BLE001 - poll until ready
                last_error = error
            if self.process.poll() is not None:
                output = ""
                if self.process.stdout is not None:
                    output = self.process.stdout.read()
                raise RuntimeError(
                    f"Bridge exited early with code {self.process.returncode}: {output}"
                )
            time.sleep(0.1)
        raise RuntimeError(f"Bridge did not become healthy: {last_error}")

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    time.sleep(0.05)
            except OSError:
                return


def start_bridge(*, port: int | None = None, extra_env: dict[str, str] | None = None) -> BridgeProc:
    port = port or free_port()
    tmp_cwd = Path(os.environ.get("TMPDIR", "/tmp")) / f"roam-bridge-{uuid.uuid4()}"
    tmp_cwd.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "ROAM_AGENT_TOKEN": AGENT_TOKEN,
            "ROAM_DEVICE_TOKEN": DEVICE_TOKEN,
            "ROAM_NOTIFIER": "mqtt",
            "ROAM_MQTT_HOST": "127.0.0.1",
            "ROAM_MQTT_PORT": "1883",
            "ROAM_BIND": "127.0.0.1",
            "ROAM_PORT": str(port),
        }
    )
    if extra_env:
        env.update(extra_env)
    process = subprocess.Popen(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "uvicorn",
            "roam_approve_bridge.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=tmp_cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    bridge = BridgeProc(
        port=port,
        process=process,
        tmp_cwd=tmp_cwd,
        base_url=f"http://127.0.0.1:{port}",
    )
    try:
        bridge.wait_healthy()
    except Exception:
        bridge.stop()
        raise
    return bridge


def mosquitto_identity() -> tuple[str, str] | None:
    try:
        cid = subprocess.check_output(
            ["docker", "compose", "ps", "-q", "mosquitto"],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
        if not cid:
            return None
        started = subprocess.check_output(
            ["docker", "inspect", "-f", "{{.State.StartedAt}}", cid],
            text=True,
        ).strip()
        return cid, started
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def create_request(
    bridge: BridgeProc,
    *,
    title: str = "Run command",
    timeout_s: int = 300,
) -> str:
    response = httpx.post(
        f"{bridge.base_url}/v1/requests",
        headers=bridge.headers("agent"),
        json={
            "agent": "devin-cli",
            "session_id": f"sess-{time.time_ns()}",
            "title": title,
            "lines": ["make test"],
            "timeout_s": timeout_s,
        },
        timeout=5.0,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def decide_request(
    bridge: BridgeProc,
    request_id: str,
    decision: str = "approve",
) -> None:
    response = httpx.post(
        f"{bridge.base_url}/v1/requests/{request_id}/decision",
        headers=bridge.headers("device"),
        json={"decision": decision, "source": "integration"},
        timeout=5.0,
    )
    assert response.status_code == 200, response.text
