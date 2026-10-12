#!/usr/bin/env python3
"""FastAPI application factory for the approval bridge."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime

from fastapi import FastAPI

from .api import router
from .config import Settings
from .models import utc_now
from .notifier.base import Notifier
from .notifier.memory import MemoryNotifier
from .notifier.mqtt import MqttNotifier
from .store import ApprovalStore


def create_app(
    settings: Settings | None = None,
    *,
    notifier: Notifier | None = None,
    clock: Callable[[], datetime] | None = None,
    sweep_interval_s: float = 1.0,
) -> FastAPI:
    settings = settings or Settings()
    if notifier is None:
        if settings.notifier == "memory":
            notifier = MemoryNotifier()
        else:
            notifier = MqttNotifier(
                settings.mqtt_host,
                settings.mqtt_port,
                is_pending=lambda request_id: store.is_pending(request_id),
            )

    store = ApprovalStore(
        clock=clock or utc_now,
        on_resolved=notifier.publish_resolved,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        notifier.start()

        async def sweep_expired() -> None:
            while True:
                await asyncio.sleep(sweep_interval_s)
                store.expire_due()

        sweeper = asyncio.create_task(sweep_expired())
        try:
            yield
        finally:
            sweeper.cancel()
            with suppress(asyncio.CancelledError):
                await sweeper
            notifier.close()

    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.notifier = notifier
    app.include_router(router)
    return app


def __getattr__(name: str) -> FastAPI:
    if name != "app":
        raise AttributeError(name)
    application = create_app()
    globals()["app"] = application
    return application
