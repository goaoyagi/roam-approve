import io
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Self

import pytest
from roam_approve_adapters import cli


class MockBridge:
    def __init__(self) -> None:
        self.post_status = 201
        self.redirect_to: str | None = None
        self.wait_status = "approved"
        self.wait_http_status = 200
        self.wait_sleep = 0.0
        self.requests: list[dict] = []
        self.auth_headers: list[str | None] = []
        self._server = self._make_server()
        self.port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _make_server(self) -> ThreadingHTTPServer:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def _send(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                outer.auth_headers.append(self.headers.get("Authorization"))
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append(json.loads(self.rfile.read(length) or b"{}"))
                if self.path == "/v1/requests":
                    if outer.redirect_to is not None:
                        self.send_response(302)
                        self.send_header("Location", outer.redirect_to)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    if outer.post_status != 201:
                        self._send(outer.post_status, {"detail": "error"})
                        return
                    self._send(201, {"id": "req-1"})
                else:
                    self._send(404, {"detail": "not found"})

            def do_GET(self) -> None:
                outer.auth_headers.append(self.headers.get("Authorization"))
                if self.path.startswith("/v1/requests/") and self.path.endswith(
                    "/wait"
                ) or "/wait?" in self.path:
                    if outer.wait_http_status != 200:
                        self._send(outer.wait_http_status, {"detail": "error"})
                        return
                    time.sleep(outer.wait_sleep)
                    self._send(200, {"status": outer.wait_status})
                else:
                    self._send(404, {"detail": "not found"})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        return server

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *args) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)


@pytest.fixture
def bridge() -> MockBridge:
    with MockBridge() as mock:
        yield mock


@pytest.fixture
def stdin_event(monkeypatch):
    event = {
        "tool_name": "exec",
        "session_id": "sess-42",
        "tool_input": {"command": "ls -la"},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    return event


def run_hook(monkeypatch, capsys, bridge: MockBridge | None, wait_s: str = "5"):
    url = bridge.url if bridge is not None else "http://127.0.0.1:1"
    monkeypatch.setenv("ROAM_BRIDGE_URL", url)
    monkeypatch.setenv("ROAM_AGENT_TOKEN", "test-token")
    monkeypatch.setenv("ROAM_WAIT_S", wait_s)
    code = cli.main(["devin-cli"])
    captured = capsys.readouterr()
    assert "test-token" not in captured.out
    assert "test-token" not in captured.err
    return code, captured


def test_approve(monkeypatch, capsys, bridge, stdin_event) -> None:
    code, captured = run_hook(monkeypatch, capsys, bridge)
    assert code == 0
    assert captured.out.strip() == '{"decision":"approve"}'
    assert "Bearer test-token" in bridge.auth_headers
    body = bridge.requests[0]
    assert body["agent"] == "devin-cli"
    assert body["title"] == "exec"
    assert body["lines"] == ["ls -la"]
    assert body["session_id"] == "sess-42"
    assert body["timeout_s"] == 5


def test_reject(monkeypatch, capsys, bridge, stdin_event) -> None:
    bridge.wait_status = "rejected"
    code, captured = run_hook(monkeypatch, capsys, bridge)
    assert code == 0
    assert (
        captured.out.strip()
        == '{"decision":"block","reason":"Rejected on M5StickC"}'
    )


def test_pending_timeout(monkeypatch, capsys, bridge, stdin_event) -> None:
    bridge.wait_status = "pending"
    bridge.wait_sleep = 0.2
    start = time.monotonic()
    code, captured = run_hook(monkeypatch, capsys, bridge, wait_s="1")
    elapsed = time.monotonic() - start
    assert code == 0
    assert captured.out == ""
    assert elapsed < 10


def test_expired(monkeypatch, capsys, bridge, stdin_event) -> None:
    bridge.wait_status = "expired"
    code, captured = run_hook(monkeypatch, capsys, bridge)
    assert code == 0
    assert captured.out == ""


def test_connection_refused(monkeypatch, capsys, stdin_event) -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("ROAM_BRIDGE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("ROAM_AGENT_TOKEN", "test-token")
    monkeypatch.setenv("ROAM_WAIT_S", "1")
    code = cli.main(["devin-cli"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert "unreachable" in captured.err
    assert "test-token" not in captured.err


def test_post_401(monkeypatch, capsys, bridge, stdin_event) -> None:
    bridge.post_status = 401
    code, captured = run_hook(monkeypatch, capsys, bridge)
    assert code == 0
    assert captured.out == ""
    assert "401" in captured.err


def test_post_422(monkeypatch, capsys, bridge, stdin_event) -> None:
    bridge.post_status = 422
    code, captured = run_hook(monkeypatch, capsys, bridge)
    assert code == 0
    assert captured.out == ""
    assert "422" in captured.err


def test_wait_404(monkeypatch, capsys, bridge, stdin_event) -> None:
    bridge.wait_http_status = 404
    code, captured = run_hook(monkeypatch, capsys, bridge)
    assert code == 0
    assert captured.out == ""
    assert "404" in captured.err


def test_missing_token(monkeypatch, capsys, bridge, stdin_event) -> None:
    monkeypatch.setenv("ROAM_BRIDGE_URL", bridge.url)
    monkeypatch.delenv("ROAM_AGENT_TOKEN", raising=False)
    code = cli.main(["devin-cli"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert bridge.requests == []


def test_invalid_stdin_json(monkeypatch, capsys, bridge) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    code, captured = run_hook(monkeypatch, capsys, bridge)
    assert code == 0
    assert captured.out == ""


def test_wait_s_clamped_to_280(monkeypatch, capsys, bridge, stdin_event) -> None:
    code, captured = run_hook(monkeypatch, capsys, bridge, wait_s="3600")
    assert code == 0
    assert captured.out.strip() == '{"decision":"approve"}'
    assert bridge.requests[0]["timeout_s"] == 280


def test_wait_s_zero_clamped_to_1(monkeypatch, capsys, bridge, stdin_event) -> None:
    code, captured = run_hook(monkeypatch, capsys, bridge, wait_s="0")
    assert code == 0
    assert captured.out.strip() == '{"decision":"approve"}'
    assert bridge.requests[0]["timeout_s"] == 1


def test_post_redirect_not_followed(
    monkeypatch, capsys, bridge, stdin_event
) -> None:
    with MockBridge() as redirect_target:
        bridge.redirect_to = f"{redirect_target.url}/v1/requests"
        code, captured = run_hook(monkeypatch, capsys, bridge)
    assert code == 0
    assert captured.out == ""
    assert "302" in captured.err
    assert redirect_target.requests == []
    assert redirect_target.auth_headers == []


def test_unknown_agent(monkeypatch, capsys, bridge, stdin_event) -> None:
    monkeypatch.setenv("ROAM_BRIDGE_URL", bridge.url)
    monkeypatch.setenv("ROAM_AGENT_TOKEN", "test-token")
    code = cli.main(["no-such-agent"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert bridge.requests == []
