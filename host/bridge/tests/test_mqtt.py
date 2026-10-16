import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from paho.mqtt import client as mqtt
from roam_approve_bridge.models import ApprovalRequest
from roam_approve_bridge.notifier.base import (
    PAYLOAD_LINE_CHARS,
    PAYLOAD_MAX_LINES,
    PAYLOAD_TITLE_CHARS,
    REQUEST_TOPIC_FILTER,
    RESOLVED_TOPIC,
    request_payload,
    request_topic,
)
from roam_approve_bridge.notifier.mqtt import MqttNotifier


def approval_request():
    return ApprovalRequest(
        id=uuid4(),
        agent="devin-cli",
        session_id="session-1",
        title="Run command",
        lines=["make test"],
        timeout_s=300,
    )


def test_mqtt_notifier_lifecycle_and_payloads(monkeypatch):
    client = MagicMock()
    client.publish.return_value = SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)
    client_factory = MagicMock(return_value=client)
    monkeypatch.setattr("roam_approve_bridge.notifier.mqtt.mqtt.Client", client_factory)

    notifier = MqttNotifier("mqtt-host", 1883)
    request = approval_request()
    notifier.start()
    notifier.publish_request(request)
    notifier.publish_resolved(request)
    notifier.close()

    client_factory.assert_called_once_with(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )
    client.connect_async.assert_called_once_with("mqtt-host", 1883)
    client.loop_start.assert_called_once_with()
    request_messages = client.publish.call_args_list
    assert request_messages[0].args[0] == request_topic(request.id)
    assert json.loads(request_messages[0].args[1]) == {
        "id": str(request.id),
        "agent": request.agent,
        "title": request.title,
        "lines": request.lines,
        "expires_at": request.expires_at.isoformat(),
    }
    assert client.publish.call_args_list[0].kwargs == {
        "qos": 1,
        "retain": True,
    }
    assert client.publish.call_args_list[1].args == (request_topic(request.id), b"")
    assert client.publish.call_args_list[1].kwargs == {
        "qos": 1,
        "retain": True,
    }
    resolved = json.loads(client.publish.call_args_list[2].args[1])
    assert resolved == {"id": str(request.id), "status": "pending"}
    assert client.publish.call_args_list[2].args[0] == RESOLVED_TOPIC
    assert client.publish.call_args_list[2].kwargs == {
        "qos": 1,
        "retain": False,
    }
    client.loop_stop.assert_called_once_with()
    client.disconnect.assert_called_once_with()


def test_request_payload_fits_device_mqtt_buffer():
    request = ApprovalRequest(
        id=uuid4(),
        agent="\u3042" * 64,
        session_id="session-1",
        title="\u3042" * 256,
        lines=["\u3042" * 256] * 32,
        timeout_s=300,
    )

    payload = request_payload(request)
    encoded = json.dumps(payload).encode()

    assert payload["title"] == "\u3042" * PAYLOAD_TITLE_CHARS
    assert payload["lines"] == ["\u3042" * PAYLOAD_LINE_CHARS] * PAYLOAD_MAX_LINES
    assert len(encoded) < 4096


def test_stale_retained_request_is_cleared(monkeypatch):
    client = MagicMock()
    client.publish.return_value = SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)
    monkeypatch.setattr(
        "roam_approve_bridge.notifier.mqtt.mqtt.Client",
        MagicMock(return_value=client),
    )
    known = str(uuid4())
    stale = str(uuid4())
    notifier = MqttNotifier("mqtt-host", 1883, is_pending=lambda rid: rid == known)

    notifier._on_connect(client, None, None, 0, None)
    client.subscribe.assert_called_once_with(REQUEST_TOPIC_FILTER, qos=1)

    for request_id in (known, stale):
        notifier._on_message(
            client,
            None,
            SimpleNamespace(
                topic=request_topic(request_id),
                payload=b"{}",
                retain=True,
            ),
        )
    client.publish.assert_called_once_with(
        request_topic(stale), b"", qos=1, retain=True
    )
