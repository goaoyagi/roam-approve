"""Helpers for full-path e2e tests."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_TOKEN = "test-token-agent-e2e"
DEVICE_TOKEN = "test-token-device-e2e"


def mqtt_reachable(host: str = "127.0.0.1", port: int = 1883, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def ensure_mosquitto() -> None:
    if mqtt_reachable():
        return
    subprocess.check_call(["docker", "compose", "up", "-d", "mosquitto"], cwd=REPO_ROOT)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if mqtt_reachable():
            return
        time.sleep(0.2)
    raise RuntimeError("mosquitto did not become reachable on 127.0.0.1:1883")


@dataclass
class ManagedProc:
    process: subprocess.Popen[str]
    name: str
    output_lines: list[str] = field(default_factory=list)
    _reader: threading.Thread | None = field(default=None, repr=False)

    @classmethod
    def spawn(
        cls,
        args: list[str],
        *,
        name: str,
        env: dict[str, str],
        cwd: Path,
    ) -> ManagedProc:
        process = subprocess.Popen(
            args,
            env=env,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        managed = cls(process=process, name=name)
        if process.stdout is not None:
            managed._reader = threading.Thread(
                target=managed._drain_stdout,
                name=f"{name}-stdout",
                daemon=True,
            )
            managed._reader.start()
        return managed

    def _drain_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.output_lines.append(line)

    def output_text(self) -> str:
        return "".join(self.output_lines)

    def stop(self) -> None:
        if self.process.poll() is not None:
            if self._reader is not None:
                self._reader.join(timeout=2)
            return
        self.process.send_signal(signal.SIGTERM)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        if self._reader is not None:
            self._reader.join(timeout=2)


@dataclass
class E2EEnv:
    bridge_url: str
    agent_token: str
    device_token: str
    mqtt_host: str
    mqtt_port: int
    repo_root: Path

    def hook_env(self, **extra: str) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "ROAM_BRIDGE_URL": self.bridge_url,
                "ROAM_AGENT_TOKEN": self.agent_token,
                "ROAM_DEVICE_TOKEN": self.device_token,
                "ROAM_MQTT_HOST": self.mqtt_host,
                "ROAM_MQTT_PORT": str(self.mqtt_port),
            }
        )
        env.update(extra)
        return env

    def device_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.device_token}"}

    def agent_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.agent_token}"}


def start_bridge() -> tuple[ManagedProc, str]:
    port = free_port()
    tmp_cwd = Path(os.environ.get("TMPDIR", "/tmp")) / f"roam-e2e-bridge-{uuid.uuid4()}"
    tmp_cwd.mkdir(parents=True, exist_ok=True)
    bridge_env = os.environ.copy()
    bridge_env.update(
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
    bridge = ManagedProc.spawn(
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
        name="bridge",
        env=bridge_env,
        cwd=tmp_cwd,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/healthz", timeout=1.0)
            if response.status_code == 200:
                return bridge, base_url
        except Exception as error:  # noqa: BLE001 - poll until ready
            last_error = error
        if bridge.process.poll() is not None:
            raise RuntimeError(f"Bridge exited early: {bridge.output_text()}")
        time.sleep(0.1)
    bridge.stop()
    raise RuntimeError(f"Bridge failed to become healthy: {last_error}")


def run_hook(
    env: E2EEnv,
    event: dict,
    *,
    wait_s: int = 30,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[bytes]:
    hook_env = env.hook_env(ROAM_WAIT_S=str(wait_s))
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(env.repo_root),
            "roam-approve-hook",
            "devin-cli",
        ],
        input=json.dumps(event).encode(),
        capture_output=True,
        env=hook_env,
        cwd=env.repo_root,
        timeout=timeout,
        check=False,
    )


def start_fake_device(env: E2EEnv, *, auto: str) -> ManagedProc:
    return ManagedProc.spawn(
        [
            "uv",
            "run",
            "--project",
            str(env.repo_root),
            "python",
            str(env.repo_root / "tools/e2e/fake_device.py"),
            "--auto",
            auto,
        ],
        name=f"fake-device-{auto}",
        env=env.hook_env(),
        cwd=env.repo_root,
    )


def sample_event(command: str = "ls -la") -> dict:
    return {
        "tool_name": "exec",
        "session_id": f"e2e-{uuid.uuid4()}",
        "tool_input": {"command": command},
    }


def find_request_by_session(env: E2EEnv, session_id: str) -> dict | None:
    response = httpx.get(
        f"{env.bridge_url}/v1/requests",
        headers=env.device_headers(),
        timeout=5.0,
    )
    assert response.status_code == 200, response.text
    matches = [
        item for item in response.json() if item.get("session_id") == session_id
    ]
    if not matches:
        return None
    return matches[0]
