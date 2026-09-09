"""Focused safety tests for the concrete HTTP egress transport."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import requests
from django.test import override_settings

from apps.config_center.domain.egress import EgressEndpoint
from apps.data_center.application.egress_service import EgressTransportResult
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.infrastructure import egress_transport as transport_module


def _context() -> EgressRequestContext:
    """Build a public-looking test target without performing DNS resolution."""

    return EgressRequestContext(
        provider_id=3,
        dataset_key="equity.price.bar",
        target_url="https://data.example.com/history",
        deployment_region="overseas_vps",
    )


def _endpoint() -> EgressEndpoint:
    """Build one resolved endpoint with non-production test credentials."""

    return EgressEndpoint(
        id=17,
        name="mainland-test-proxy",
        region="mainland",
        protocol="http",
        host="proxy.example.test",
        port=8080,
        username="proxy-user",
        password="proxy-password",
        enabled=True,
        concurrency_limit=4,
        username_configured=True,
        password_configured=True,
    )


class _Response:
    """Small requests response double with bounded streaming support."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        body: bytes = b'{"ok":true}',
        redirect: bool = False,
        read_raises: bool = False,
        content_length: bool = True,
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.is_redirect = redirect
        self.is_permanent_redirect = False
        self.headers = {"Content-Length": str(len(body))} if content_length else {}
        self.encoding = "utf-8"
        self.read_raises = read_raises
        self.closed = False

    def iter_content(self, *, chunk_size: int) -> Iterator[bytes]:
        """Yield one response body chunk or reject an unexpected body read."""

        del chunk_size
        if self.read_raises:
            raise AssertionError("the transport should not read an HTTP error body")
        yield self.body

    def close(self) -> None:
        """Record response cleanup."""

        self.closed = True


class _Session:
    """Capture one mocked requests session without opening a socket."""

    def __init__(
        self,
        response: _Response | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.trust_env = True
        self.proxies: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.closed = False

    def mount(self, prefix: str, adapter: object) -> None:
        """Record the session-scoped address-pinning adapter."""
        self.adapter_prefix = prefix
        self.adapter = adapter

    def get(self, url: str, **kwargs: object) -> _Response:
        """Return the configured response or raise the configured request error."""

        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("test session has no response")
        return self.response

    def close(self) -> None:
        """Record session cleanup."""

        self.closed = True


def _patch_request(
    monkeypatch: pytest.MonkeyPatch,
    session: _Session,
    *,
    endpoint: EgressEndpoint | None = None,
) -> None:
    """Patch network and shared-state gates so one test remains local and bounded."""

    monkeypatch.setattr(
        transport_module,
        "_validate_public_target",
        lambda _url: SimpleNamespace(
            url="https://93.184.216.34/history",
            scheme="https",
            host_header="data.example.com",
            adapter=None,
        ),
    )
    monkeypatch.setattr(transport_module.requests, "Session", lambda: session)
    monkeypatch.setattr(transport_module._shared_state, "circuit_open", lambda _key: False)
    monkeypatch.setattr(transport_module._shared_state, "acquire", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(transport_module._shared_state, "success", lambda _key: None)
    monkeypatch.setattr(transport_module._shared_state, "failure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transport_module._shared_state, "release", lambda _key: None)
    if endpoint is not None:
        monkeypatch.setattr(transport_module, "get_egress_endpoint", lambda _id: endpoint)


def _request_payload(
    transport: transport_module.EgressHttpTransport,
    context: EgressRequestContext,
    *,
    egress_id: int | None = None,
) -> tuple[EgressTransportResult, object | None]:
    """Issue one JSON GET through the public payload entry point."""

    return transport.request_payload(
        context,
        egress_id=egress_id,
        request_id=uuid4(),
        attempt=1,
        method="GET",
        params={"symbol": "600000"},
        json_body=None,
        headers={"X-Test": "egress"},
        expect_json=True,
    )


def test_explicit_proxy_ignores_no_proxy_for_https_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The selected proxy remains mandatory even with a NO_PROXY wildcard."""

    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    endpoint = _endpoint()
    response = _Response()
    session = _Session(response=response)
    _patch_request(monkeypatch, session, endpoint=endpoint)

    result, payload = _request_payload(
        transport_module.EgressHttpTransport(max_attempts=1),
        _context(),
        egress_id=endpoint.id,
    )

    expected_proxy = "http://proxy-user:proxy-password@proxy.example.test:8080"
    assert result.outcome == "success"
    assert payload == {"ok": True}
    assert session.trust_env is False
    assert session.proxies == {"http": expected_proxy, "https": expected_proxy}
    assert session.calls[0][0] == "https://93.184.216.34/history"
    assert session.calls[0][1]["headers"]["Host"] == "data.example.com"
    assert session.adapter_prefix == "https://"
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["stream"] is True
    assert response.closed is True
    assert session.closed is True


@pytest.mark.parametrize("status_code", [401, 403, 429])
def test_auth_and_rate_statuses_are_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    """Authentication and quota responses stop the route without retry."""

    response = _Response(status_code=status_code, body=b"secret-error", read_raises=True)
    session = _Session(response=response)
    _patch_request(monkeypatch, session)

    result, payload = _request_payload(
        transport_module.EgressHttpTransport(max_attempts=2), _context()
    )

    assert result.outcome == "failed"
    assert result.error_code == f"EGRESS_HTTP_{status_code}"
    assert result.status_code == status_code
    assert result.retryable is False
    assert payload is None
    assert len(session.calls) == 1
    assert response.closed is True


@pytest.mark.parametrize(
    ("status_code", "redirect", "error_code"),
    [(404, False, "EGRESS_HTTP_404"), (302, True, "EGRESS_REDIRECT_BLOCKED")],
)
def test_http_errors_and_redirects_are_failed_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    redirect: bool,
    error_code: str,
) -> None:
    """Non-success responses never become successful provider payloads."""

    response = _Response(status_code=status_code, redirect=redirect, read_raises=True)
    session = _Session(response=response)
    _patch_request(monkeypatch, session)

    result, payload = _request_payload(
        transport_module.EgressHttpTransport(max_attempts=2), _context()
    )

    assert result.outcome == "failed"
    assert result.error_code == error_code
    assert result.retryable is False
    assert payload is None
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    ("error", "error_code", "retryable"),
    [
        (requests.exceptions.SSLError("certificate failure"), "EGRESS_TLS_ERROR", False),
        (
            requests.exceptions.ConnectionError("connection refused"),
            "EGRESS_CONNECTION_ERROR",
            True,
        ),
    ],
    ids=["tls", "connection"],
)
def test_transport_error_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    error_code: str,
    retryable: bool,
) -> None:
    """TLS failures stop while connection failures can use the caller budget."""

    session = _Session(error=error)
    _patch_request(monkeypatch, session)
    failure = Mock()
    monkeypatch.setattr(transport_module._shared_state, "failure", failure)

    result, payload = _request_payload(
        transport_module.EgressHttpTransport(max_attempts=2), _context()
    )

    assert result.outcome == "failed"
    assert result.error_code == error_code
    assert result.retryable is retryable
    assert payload is None
    assert failure.call_count == (1 if retryable else 0)
    assert session.closed is True


def test_oversized_json_body_is_failed_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A streamed response beyond the configured ceiling cannot be accepted."""

    response = _Response(body=b"x" * 1025, content_length=False)
    session = _Session(response=response)
    _patch_request(monkeypatch, session)
    transport = transport_module.EgressHttpTransport(max_attempts=1, max_response_bytes=1024)

    # This direct private call keeps the test focused on the configured body
    # ceiling while the other cases exercise request_payload above.
    result, payload = transport._request_once(
        _context(),
        egress_id=None,
        attempt=1,
        expect_json=True,
        max_response_bytes=1024,
    )

    assert result.outcome == "failed"
    assert result.error_code == "EGRESS_INVALID_PAYLOAD"
    assert result.retryable is False
    assert payload is None


@override_settings(DEBUG=False, REDIS_URL="")
def test_production_redis_unavailable_blocks_before_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production mode refuses an independent local concurrency counter."""

    state = transport_module._SharedEgressState()
    monkeypatch.setattr(transport_module, "_shared_state", state)
    monkeypatch.setattr(transport_module, "_validate_public_target", lambda _url: None)
    monkeypatch.setattr(
        transport_module.requests,
        "Session",
        lambda: pytest.fail("HTTP session must not start when Redis is unavailable"),
    )
    monkeypatch.setattr(state, "circuit_open", lambda _key: False)

    result, payload = transport_module.EgressHttpTransport(max_attempts=1)._request_once(
        _context(), egress_id=None, attempt=1, expect_json=True
    )

    assert result.outcome == "blocked"
    assert result.error_code == "EGRESS_SHARED_STATE_UNAVAILABLE"
    assert result.retryable is True
    assert payload is None
    assert state.backend_unavailable() is True
    assert state._local_counts == {}
