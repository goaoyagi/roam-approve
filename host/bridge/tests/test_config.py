import pytest
from pydantic import ValidationError
from roam_approve_bridge.config import Settings


def test_defaults_with_explicit_tokens(monkeypatch):
    for name in (
        "ROAM_BIND",
        "ROAM_PORT",
        "ROAM_MQTT_HOST",
        "ROAM_MQTT_PORT",
        "ROAM_NOTIFIER",
        "ROAM_AGENT_TOKEN",
        "ROAM_DEVICE_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(
        agent_token="test-token",
        device_token="test-token-device",
        _env_file=None,
    )
    assert settings.bind == "127.0.0.1"
    assert settings.port == 8000
    assert settings.mqtt_host == "127.0.0.1"
    assert settings.mqtt_port == 1883
    assert settings.notifier == "mqtt"


def test_equal_tokens_are_rejected_without_echoing_value():
    with pytest.raises(ValidationError) as error:
        Settings(
            agent_token="test-token",
            device_token="test-token",
            _env_file=None,
        )
    assert "test-token" not in str(error.value)


@pytest.mark.parametrize("field", ["agent_token", "device_token"])
def test_empty_tokens_are_rejected(field):
    values = {
        "agent_token": "test-token",
        "device_token": "test-token-device",
        field: "",
        "_env_file": None,
    }
    with pytest.raises(ValidationError):
        Settings(**values)
