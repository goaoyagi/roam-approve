import asyncio
import time
from uuid import UUID, uuid4

import pytest
from roam_approve_bridge.notifier.base import RESOLVED_TOPIC, request_topic


def request_payload(**updates):
    payload = {
        "agent": "devin-cli",
        "session_id": "session-1",
        "title": "Run command",
        "lines": ["make test"],
        "timeout_s": 300,
    }
    payload.update(updates)
    return payload


@pytest.mark.parametrize(
    ("path", "method", "token"),
    [
        ("/v1/requests", "post", None),
        ("/v1/requests", "post", "wrong-token"),
        ("/v1/requests", "post", "test-token-device"),
        (f"/v1/requests/{uuid4()}/wait", "get", None),
        (f"/v1/requests/{uuid4()}/wait", "get", "wrong-token"),
        (f"/v1/requests/{uuid4()}/wait", "get", "test-token-device"),
        ("/v1/requests", "get", "test-token"),
        (f"/v1/requests/{uuid4()}/decision", "post", "test-token"),
    ],
)
def test_endpoint_authentication(client, path, method, token):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = getattr(client, method)(path, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_basic_scheme_is_unauthorized(client):
    response = client.post(
        "/v1/requests",
        headers={"Authorization": "Basic test-token"},
        json=request_payload(),
    )
    assert response.status_code == 401


def test_healthz_does_not_require_auth(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_request_publishes_summary(client, agent_headers, notifier):
    response = client.post(
        "/v1/requests",
        headers=agent_headers,
        json=request_payload(),
    )
    assert response.status_code == 201
    assert isinstance(UUID(response.json()["id"]), UUID)
    assert len(notifier.messages) == 1
    message = notifier.messages[0]
    assert message.topic == request_topic(response.json()["id"])
    assert message.retain is True
    assert set(message.payload) == {
        "id",
        "agent",
        "title",
        "lines",
        "expires_at",
    }


def test_create_validation_rejects_zero_timeout(client, agent_headers):
    response = client.post(
        "/v1/requests",
        headers=agent_headers,
        json=request_payload(timeout_s=0),
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "updates",
    [
        {"agent": ""},
        {"session_id": ""},
        {"title": ""},
        {"lines": ["x" * 257]},
        {"lines": ["line"] * 33},
        {"timeout_s": 3601},
    ],
)
def test_create_validation_enforces_field_limits(client, agent_headers, updates):
    response = client.post(
        "/v1/requests",
        headers=agent_headers,
        json=request_payload(**updates),
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("decision", "status", "reason"),
    [
        ("approve", "approved", None),
        ("reject", "rejected", "rejected by device"),
    ],
)
def test_wait_returns_existing_decision(
    client,
    agent_headers,
    device_headers,
    decision,
    status,
    reason,
):
    created = client.post(
        "/v1/requests",
        headers=agent_headers,
        json=request_payload(),
    ).json()
    client.post(
        f"/v1/requests/{created['id']}/decision",
        headers=device_headers,
        json={"decision": decision},
    )

    response = client.get(
        f"/v1/requests/{created['id']}/wait",
        headers=agent_headers,
    )
    assert response.json() == {"status": status, "reason": reason}


@pytest.mark.anyio
async def test_wait_pending_then_decision_returns_approved(
    async_client,
    agent_headers,
    device_headers,
):
    async with async_client as client:
        created = await client.post(
            "/v1/requests",
            headers=agent_headers,
            json=request_payload(),
        )
        request_id = created.json()["id"]
        waiting = asyncio.create_task(
            client.get(
                f"/v1/requests/{request_id}/wait",
                headers=agent_headers,
                params={"timeout_s": 5},
            )
        )
        await asyncio.sleep(0.01)
        decision = await client.post(
            f"/v1/requests/{request_id}/decision",
            headers=device_headers,
            json={"decision": "approve"},
        )
        assert decision.status_code == 200
        response = await waiting
        assert response.json() == {"status": "approved", "reason": None}


@pytest.mark.anyio
async def test_wait_short_timeout_returns_pending(async_client, agent_headers):
    async with async_client as client:
        created = await client.post(
            "/v1/requests",
            headers=agent_headers,
            json=request_payload(),
        )
        response = await client.get(
            f"/v1/requests/{created.json()['id']}/wait",
            headers=agent_headers,
            params={"timeout_s": 0.05},
        )
    assert response.json() == {"status": "pending", "reason": None}


def test_wait_after_expiration_publishes_resolution(
    client,
    agent_headers,
    notifier,
    clock,
):
    created = client.post(
        "/v1/requests",
        headers=agent_headers,
        json=request_payload(timeout_s=1),
    ).json()
    clock.advance(2)
    response = client.get(
        f"/v1/requests/{created['id']}/wait",
        headers=agent_headers,
    )
    assert response.json() == {
        "status": "expired",
        "reason": "expired before decision",
    }
    assert notifier.messages[-2].topic == request_topic(created["id"])
    assert notifier.messages[-2].payload is None
    assert notifier.messages[-2].retain is True
    assert notifier.messages[-1].topic == RESOLVED_TOPIC
    assert notifier.messages[-1].payload == {
        "id": created["id"],
        "status": "expired",
    }
    assert notifier.messages[-1].retain is False


def test_decision_publishes_clear_and_resolved_message(
    client,
    agent_headers,
    device_headers,
    notifier,
):
    created = client.post(
        "/v1/requests",
        headers=agent_headers,
        json=request_payload(),
    ).json()
    response = client.post(
        f"/v1/requests/{created['id']}/decision",
        headers=device_headers,
        json={"decision": "approve"},
    )
    assert response.status_code == 200
    assert response.json()["decided_by"] == "device"
    assert [message.topic for message in notifier.messages[-2:]] == [
        request_topic(created["id"]),
        RESOLVED_TOPIC,
    ]
    assert notifier.messages[-2].payload is None
    assert notifier.messages[-2].retain is True
    assert notifier.messages[-1].payload == {
        "id": created["id"],
        "status": "approved",
    }
    assert notifier.messages[-1].retain is False


def test_second_decision_returns_conflict(client, agent_headers, device_headers):
    created = client.post(
        "/v1/requests",
        headers=agent_headers,
        json=request_payload(),
    ).json()
    path = f"/v1/requests/{created['id']}/decision"
    assert client.post(
        path,
        headers=device_headers,
        json={"decision": "approve"},
    ).status_code == 200
    assert client.post(
        path,
        headers=device_headers,
        json={"decision": "reject"},
    ).status_code == 409


def test_decision_after_expiration_returns_conflict(
    client,
    agent_headers,
    device_headers,
    clock,
):
    created = client.post(
        "/v1/requests",
        headers=agent_headers,
        json=request_payload(timeout_s=1),
    ).json()
    clock.advance(2)
    response = client.post(
        f"/v1/requests/{created['id']}/decision",
        headers=device_headers,
        json={"decision": "approve"},
    )
    assert response.status_code == 409


@pytest.mark.parametrize("endpoint", ["wait", "decision"])
def test_unknown_request_returns_not_found(
    client,
    agent_headers,
    device_headers,
    endpoint,
):
    request_id = uuid4()
    if endpoint == "wait":
        response = client.get(
            f"/v1/requests/{request_id}/wait",
            headers=agent_headers,
        )
    else:
        response = client.post(
            f"/v1/requests/{request_id}/decision",
            headers=device_headers,
            json={"decision": "approve"},
        )
    assert response.status_code == 404


def test_list_requests_filters_by_status(client, agent_headers, device_headers):
    pending = client.post(
        "/v1/requests",
        headers=agent_headers,
        json=request_payload(),
    ).json()
    approved = client.post(
        "/v1/requests",
        headers=agent_headers,
        json=request_payload(session_id="session-2"),
    ).json()
    client.post(
        f"/v1/requests/{approved['id']}/decision",
        headers=device_headers,
        json={"decision": "approve"},
    )

    response = client.get(
        "/v1/requests",
        headers=device_headers,
        params={"status": "pending"},
    )
    assert [item["id"] for item in response.json()] == [pending["id"]]


@pytest.mark.anyio
async def test_wait_expires_after_clock_advance(
    async_client,
    agent_headers,
    clock,
    notifier,
):
    async with async_client as client:
        created = await client.post(
            "/v1/requests",
            headers=agent_headers,
            json=request_payload(timeout_s=1),
        )
        clock.advance(2)
        response = await client.get(
            f"/v1/requests/{created.json()['id']}/wait",
            headers=agent_headers,
        )
    assert response.json()["status"] == "expired"
    assert notifier.messages[-1].topic == RESOLVED_TOPIC


def test_sweeper_expires_request_without_waiting(
    settings,
    notifier,
    clock,
    agent_headers,
):
    from fastapi.testclient import TestClient
    from roam_approve_bridge.main import create_app

    app = create_app(
        settings,
        notifier=notifier,
        clock=clock,
        sweep_interval_s=0.01,
    )
    with TestClient(app) as client:
        created = client.post(
            "/v1/requests",
            headers=agent_headers,
            json=request_payload(timeout_s=1),
        ).json()
        clock.advance(2)
        for _ in range(50):
            if notifier.messages[-1].topic == RESOLVED_TOPIC:
                break
            time.sleep(0.01)
        assert notifier.messages[-1].payload == {
            "id": created["id"],
            "status": "expired",
        }
        listed = client.get(
            "/v1/requests",
            headers={"Authorization": "Bearer test-token-device"},
        ).json()
        expired = next(item for item in listed if item["id"] == created["id"])
        assert expired["status"] == "expired"
        assert notifier.messages[-1].topic == RESOLVED_TOPIC
