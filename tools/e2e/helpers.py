"""Helpers for full-path e2e tests."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
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

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.send_signal(signal.SIGTERM)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


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
    bridge = ManagedProc(
        subprocess.Popen(
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
            env=bridge_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ),
        name="bridge",
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
            output = bridge.process.stdout.read() if bridge.process.stdout else ""
            raise RuntimeError(f"Bridge exited early: {output}")
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
    return ManagedProc(
        subprocess.Popen(
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
            env=env.hook_env(),
            cwd=env.repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ),
        name=f"fake-device-{auto}",
    )


def sample_event(command: str = "ls -la") -> dict:
    return {
        "tool_name": "exec",
        "session_id": f"e2e-{uuid.uuid4()}",
        "tool_input": {"command": command},
    }
