"""Fixtures for full-path e2e tests (hook → Bridge → MQTT → fake device)."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_E2E_DIR = Path(__file__).resolve().parent
if str(_E2E_DIR) not in sys.path:
    sys.path.insert(0, str(_E2E_DIR))

from helpers import (
    AGENT_TOKEN,
    DEVICE_TOKEN,
    REPO_ROOT,
    E2EEnv,
    ensure_mosquitto,
    start_bridge,
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "e2e: full end-to-end path with mosquitto, Bridge, and fake device",
    )


@pytest.fixture(scope="module")
def e2e_stack() -> Iterator[E2EEnv]:
    ensure_mosquitto()
    bridge, base_url = start_bridge()
    try:
        yield E2EEnv(
            bridge_url=base_url,
            agent_token=AGENT_TOKEN,
            device_token=DEVICE_TOKEN,
            mqtt_host="127.0.0.1",
            mqtt_port=1883,
            repo_root=REPO_ROOT,
        )
    finally:
        bridge.stop()
