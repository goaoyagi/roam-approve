"""Fixtures for Bridge + real mosquitto integration tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from .helpers import (
    BridgeProc,
    MqttObserver,
    mqtt_reachable,
    start_bridge,
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: needs a live MQTT broker (skip when unreachable)",
    )


@pytest.fixture(scope="module")
def require_broker() -> None:
    if not mqtt_reachable():
        pytest.skip("MQTT broker is not reachable on 127.0.0.1:1883")


@pytest.fixture
def observer(require_broker: None) -> Iterator[MqttObserver]:
    client = MqttObserver()
    client.start()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def bridge(require_broker: None) -> Iterator[BridgeProc]:
    proc = start_bridge()
    try:
        yield proc
    finally:
        proc.stop()
