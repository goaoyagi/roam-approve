#!/usr/bin/env python3
"""MQTT approval request notifier."""

import json
import logging

import paho.mqtt.client as mqtt

from ..models import ApprovalRequest
from .base import (
    REQUEST_TOPIC,
    RESOLVED_TOPIC,
    request_payload,
    resolved_payload,
)

logger = logging.getLogger(__name__)


class MqttNotifier:
    def __init__(self, host: str, port: int) -> None:
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        self._host = host
        self._port = port

    def start(self) -> None:
        self._client.connect_async(self._host, self._port)
        self._client.loop_start()

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def publish_request(self, request: ApprovalRequest) -> None:
        self._publish(
            REQUEST_TOPIC,
            json.dumps(request_payload(request)),
            retain=True,
        )

    def publish_resolved(self, request: ApprovalRequest) -> None:
        self._publish(REQUEST_TOPIC, b"", retain=True)
        self._publish(
            RESOLVED_TOPIC,
            json.dumps(resolved_payload(request)),
            retain=False,
        )

    def _publish(self, topic: str, payload: str | bytes, *, retain: bool) -> None:
        info = self._client.publish(topic, payload, qos=1, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("MQTT publish failed with return code %s", info.rc)
