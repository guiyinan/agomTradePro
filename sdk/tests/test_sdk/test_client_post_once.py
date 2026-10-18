"""Tests for the SDK's single-attempt POST operation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import TypedDict
from unittest.mock import Mock

import pytest
from requests import Session

from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import AgomTradeProAPIError, ServerError
from agomtradepro.transport import use_request_transport


class _Attempt(TypedDict):
    path: str
    status: int
    idempotency_key: str | None
    cookie: str
    csrf: str


@contextmanager
def _serve_statuses(statuses: list[int]) -> Iterator[tuple[str, list[_Attempt]]]:
    """Serve deterministic local POST responses and retain each real HTTP attempt."""
    attempts: list[_Attempt] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            index = len(attempts)
            status = statuses[min(index, len(statuses) - 1)]
            content_length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(content_length)
            attempts.append(
                {
                    "path": self.path,
                    "status": status,
                    "idempotency_key": self.headers.get("Idempotency-Key"),
                    "cookie": self.headers.get("Cookie", ""),
                    "csrf": self.headers.get("X-CSRFToken", ""),
                }
            )
            body = b'{"code":"test_response","success":true}'
            self.send_response(status)
            if status == 307:
                self.send_header("Location", "/redirect-target/")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", attempts
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_post_once_does_not_retry_server_error() -> None:
    """One 503 response raises once instead of resending an unkeyed POST."""
    with _serve_statuses([503, 201]) as (base_url, attempts):
        client = AgomTradeProClient(
            base_url=base_url,
            api_token="test-token",
            max_retries=2,
        )
        try:
            with pytest.raises(ServerError) as caught:
                client.post_once("api/account/transactions/", json={"asset_code": "ONCE.SZ"})
        finally:
            client.close()

    assert caught.value.status_code == 503
    assert [attempt["status"] for attempt in attempts] == [503]
    assert [attempt["path"] for attempt in attempts] == ["/api/account/transactions/"]


def test_post_once_does_not_follow_redirects() -> None:
    """A 307 is returned as an error; the write body is not sent to another path."""
    with _serve_statuses([307, 201]) as (base_url, attempts):
        client = AgomTradeProClient(
            base_url=base_url,
            api_token="test-token",
            max_retries=2,
        )
        try:
            with pytest.raises(AgomTradeProAPIError) as caught:
                client.post_once("api/account/capital-flows/", json={"amount": "1.00"})
        finally:
            client.close()

    assert caught.value.status_code == 307
    assert [attempt["path"] for attempt in attempts] == ["/api/account/capital-flows/"]


def test_regular_keyed_post_keeps_its_existing_retry_path() -> None:
    """Default POST behavior and caller-supplied idempotency headers remain unchanged."""
    with _serve_statuses([503, 201]) as (base_url, attempts):
        client = AgomTradeProClient(
            base_url=base_url,
            api_token="test-token",
            max_retries=1,
        )
        try:
            result = client.post(
                "api/events/replay/commit/",
                json={"event_id": "event-1"},
                idempotency_key="existing-canonical-key",
            )
        finally:
            client.close()

    assert result["success"] is True
    assert [attempt["status"] for attempt in attempts] == [503, 201]
    assert [attempt["idempotency_key"] for attempt in attempts] == [
        "existing-canonical-key",
        "existing-canonical-key",
    ]


def test_post_once_reuses_authenticated_session_cookies_and_closes_temporary_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session-auth writes copy cookies and close their temporary pool promptly."""
    with _serve_statuses([201]) as (base_url, attempts):

        def install_test_login(client: AgomTradeProClient) -> None:
            client._session.cookies.set("sessionid", "session-cookie")
            client._session.cookies.set("csrftoken", "csrf-cookie")

        monkeypatch.setattr(AgomTradeProClient, "_authenticate_with_session", install_test_login)
        client = AgomTradeProClient(
            base_url=base_url,
            username="owner",
            password="secret",
            max_retries=1,
        )
        primary_close = Mock(wraps=client._session.close)
        monkeypatch.setattr(client._session, "close", primary_close)
        factory = client._create_single_attempt_session
        sessions: list[Session] = []
        temp_close_calls: list[Mock] = []

        def tracked_session_factory() -> Session:
            session = factory()
            close_call = Mock(wraps=session.close)
            monkeypatch.setattr(session, "close", close_call)
            sessions.append(session)
            temp_close_calls.append(close_call)
            return session

        monkeypatch.setattr(client, "_create_single_attempt_session", tracked_session_factory)
        client.post_once("api/account/transactions/", json={"asset_code": "COOKIE.SZ"})
        assert len(sessions) == 1
        assert temp_close_calls[0].call_count == 1
        primary_close.assert_not_called()
        assert "sessionid=session-cookie" in attempts[0]["cookie"]
        assert attempts[0]["csrf"] == "csrf-cookie"
        assert client._session.cookies.get("csrftoken") == "csrf-cookie"
        client.close()

    primary_close.assert_called_once()


def test_post_once_calls_an_injected_transport_once() -> None:
    """SDK makes one call to an injected transport; its internal retry policy is external."""
    transport = Mock()
    transport.request.return_value = Mock(
        status_code=503,
        json=lambda: {"code": "upstream_unavailable"},
    )
    client = AgomTradeProClient(base_url="http://test.invalid", api_token="test-token")
    try:
        with use_request_transport(transport):
            with pytest.raises(ServerError) as caught:
                client.post_once("api/account/transactions/", json={"asset_code": "ONCE.SZ"})
    finally:
        client.close()

    assert caught.value.status_code == 503
    transport.request.assert_called_once()
