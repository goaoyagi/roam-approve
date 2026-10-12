from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from roam_approve_bridge.config import Settings
from roam_approve_bridge.main import create_app
from roam_approve_bridge.notifier.memory import MemoryNotifier


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2025, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        agent_token="test-token",
        device_token="test-token-device",
        notifier="memory",
        _env_file=None,
    )


@pytest.fixture
def notifier() -> MemoryNotifier:
    return MemoryNotifier()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def app(settings: Settings, notifier: MemoryNotifier, clock: FakeClock) -> FastAPI:
    return create_app(settings, notifier=notifier, clock=clock)


@pytest.fixture
def client(app: FastAPI):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def agent_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def device_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token-device"}


@pytest.fixture
def async_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
