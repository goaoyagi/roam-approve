#!/usr/bin/env python3
"""Bridge configuration."""

from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ROAM_",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    bind: str = "127.0.0.1"
    port: int = 8000
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    notifier: Literal["mqtt", "memory"] = "mqtt"
    agent_token: SecretStr
    device_token: SecretStr

    @field_validator("agent_token", "device_token")
    @classmethod
    def validate_token(cls, token: SecretStr) -> SecretStr:
        if not token.get_secret_value():
            raise ValueError("tokens must not be empty")
        return token

    @model_validator(mode="after")
    def validate_separate_tokens(self) -> "Settings":
        if self.agent_token.get_secret_value() == self.device_token.get_secret_value():
            raise ValueError("agent and device tokens must be different")
        return self
