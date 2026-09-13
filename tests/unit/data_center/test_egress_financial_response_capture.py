"""Contracts for the opt-in financial raw-response egress seam."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseScope,
)
from apps.data_center.infrastructure import egress_transport as transport_module


class _Response:
    """Small streamed response double that exposes cleanup and read counts."""

    status_code = 200
    is_redirect = False
    is_permanent_redirect = False

    def __init__(
        self,
        body: bytes,
        *,
        headers: Mapping[str, str] | None = None,
        fail_read: bool = False,
    ) -> None:
        self.headers = dict(headers or {"Content-Length": str(len(body))})
        self._chunks = (body[:3], body[3:])
        self._fail_read = fail_read
        self.iter_calls = 0
        self.closed = False

    def iter_content(self, *, chunk_size: int) -> Iterable[bytes]:
        """Yield fixed chunks and record that the body was consumed once."""

        del chunk_size
        self.iter_calls += 1
        if self._fail_read:
            raise RuntimeError("private upstream detail")
        yield from self._chunks

    def close(self) -> None:
        """Record the transport cleanup call."""

        self.closed = True


class _Session:
    """Session double retaining only safe request options for assertions."""

    def __init__(self, response: _Response) -> None:
        self.response = response
        self.trust_env = True
        self.proxies: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.closed = False

    def mount(self, scheme: str, adapter: object) -> None:
        """Accept the configured adapter without making a network call."""

        del scheme, adapter

    def get(self, url: str, **kwargs: object) -> _Response:
        """Return the injected response and capture bounded request options."""

        self.calls.append((url, kwargs))
        return self.response

    def post(self, url: str, **kwargs: object) -> _Response:
        """POST is unsupported by this focused GET test double."""

        del url, kwargs
        raise AssertionError("the financial capture contract should use GET here")

    def close(self) -> None:
        """Record the transport cleanup call."""

        self.closed = True


def _context() -> EgressRequestContext:
    """Build a non-sensitive financial egress context for one test."""

    return EgressRequestContext(
        provider_id=3,
        dataset_key="equity.financial.fact",
        target_url="https://data.example.com/financial",
        deployment_region="overseas",
    )


def _scopes() -> tuple[FinancialRequestScope, FinancialResponseScope]:
    """Build caller-declared request and response dimensions."""

    return (
        FinancialRequestScope(
            provider_name="akshare",
            dataset_key="equity.financial.fact",
            asset_code="000001.SZ",
            period_limit=8,
        ),
        FinancialResponseScope(
            asset_codes=("000001.SZ",),
            period_ends=(),
            row_count=0,
        ),
    )


def _install_transport_doubles(monkeypatch, response: _Response) -> tuple[_Session, list[str]]:
    """Install a safe route and local limiter doubles without network access."""

    session = _Session(response)
    releases: list[str] = []
    target = SimpleNamespace(
        scheme="https",
        host_header="data.example.com",
        adapter=object(),
        url="https://data.example.com/financial",
    )
    monkeypatch.setattr(transport_module.requests, "Session", lambda: session)
    monkeypatch.setattr(transport_module, "_validate_public_target", lambda _url: target)
    monkeypatch.setattr(transport_module._shared_state, "circuit_open", lambda _key: False)
    monkeypatch.setattr(transport_module._shared_state, "acquire", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        transport_module._shared_state,
        "release",
        lambda key: releases.append(key),
    )
    return session, releases


def _capture(
    transport: transport_module.EgressHttpTransport,
    request_scope: FinancialRequestScope,
    response_scope: FinancialResponseScope,
) -> tuple[object, object | None]:
    """Call the explicit opt-in method with one bounded request."""

    return transport.request_financial_response(
        _context(),
        egress_id=None,
        request_id=uuid4(),
        attempt=1,
        method="GET",
        params={"period_limit": 8},
        json_body=None,
        headers={"X-Test": "bounded"},
        request_scope=request_scope,
        response_scope=response_scope,
    )


def test_financial_response_captures_exact_body_once_and_keeps_scope_declared(
    monkeypatch,
) -> None:
    """The opt-in method returns strict JSON plus exact raw-body evidence."""

    body = b'{"result":{"value":1e400}}'
    response = _Response(body)
    session, releases = _install_transport_doubles(monkeypatch, response)
    request_scope, response_scope = _scopes()
    before = datetime.now(UTC)

    result, captured = _capture(
        transport_module.EgressHttpTransport(max_attempts=1), request_scope, response_scope
    )

    after = datetime.now(UTC)
    assert result.outcome == "success"
    assert result.status_code == 200
    assert captured is not None
    assert captured.evidence.body_sha256 == (
        "a53073c03da6e35608067f3a030fd6baba056cd22c1ce4e6d16380ef6d5e2478"
    )
    assert captured.evidence.body_size_bytes == len(body)
    assert before <= captured.evidence.response_completed_at <= after
    assert captured.evidence.request_scope == request_scope
    assert captured.evidence.response_scope == response_scope
    assert captured.evidence.to_dict()["response_scope_basis"] == "caller_declared"
    assert captured.payload == {"result": {"value": Decimal("1e400")}}
    assert response.iter_calls == 1
    assert response.closed is True
    assert session.closed is True
    assert len(releases) == 1
    assert session.trust_env is False
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["stream"] is True


def test_financial_scope_mismatch_blocks_before_acquiring_http_slot(monkeypatch) -> None:
    """A caller cannot bind financial evidence to another routed dataset."""

    response = _Response(b'{"value":1}')
    session, releases = _install_transport_doubles(monkeypatch, response)
    request_scope, response_scope = _scopes()
    request_scope = FinancialRequestScope(
        provider_name=request_scope.provider_name,
        dataset_key="equity.price.bar",
        asset_code=request_scope.asset_code,
        period_limit=request_scope.period_limit,
    )

    result, captured = _capture(
        transport_module.EgressHttpTransport(max_attempts=1), request_scope, response_scope
    )

    assert result.outcome == "blocked"
    assert result.error_code == "EGRESS_FINANCIAL_SCOPE_INVALID"
    assert result.retryable is False
    assert captured is None
    assert session.calls == []
    assert releases == []


def test_financial_capture_rejects_body_over_transport_limit(monkeypatch) -> None:
    """The opt-in path applies the transport byte ceiling before decoding."""

    response = _Response(b"x" * 1025, headers={"Content-Length": "1025"})
    session, releases = _install_transport_doubles(monkeypatch, response)
    request_scope, response_scope = _scopes()

    result, captured = _capture(
        transport_module.EgressHttpTransport(max_attempts=1, max_response_bytes=1024),
        request_scope,
        response_scope,
    )

    assert result.outcome == "failed"
    assert result.error_code == "EGRESS_FINANCIAL_RESPONSE_CAPTURE_FAILED"
    assert result.retryable is False
    assert captured is None
    assert response.iter_calls == 0
    assert response.closed is True
    assert session.closed is True
    assert len(releases) == 1


@pytest.mark.parametrize(
    ("body", "headers", "fail_read"),
    [
        (b'{"value":NaN}', {"Content-Length": "13"}, False),
        (b'{"value":1,"value":2}', {"Content-Length": "21"}, False),
        (b'{"value":1}', {"Content-Length": "99"}, False),
        (b'{"value":1}', {"Content-Encoding": "GZip"}, False),
        (b'{"value":1}', {"Content-Length": "-1"}, False),
        (
            b'{"value":1}',
            {"Content-Length": "11", "content-length": "11"},
            False,
        ),
        (b'{"value":1}', {}, True),
    ],
)
def test_financial_capture_failures_are_sanitized_nonretryable_and_cleanup(
    monkeypatch,
    body: bytes,
    headers: Mapping[str, str],
    fail_read: bool,
) -> None:
    """Capture validation never exposes body details and always releases its slot."""

    response = _Response(body, headers=headers, fail_read=fail_read)
    session, releases = _install_transport_doubles(monkeypatch, response)
    request_scope, response_scope = _scopes()

    result, captured = _capture(
        transport_module.EgressHttpTransport(max_attempts=1), request_scope, response_scope
    )

    assert result.outcome == "failed"
    assert result.error_code == "EGRESS_FINANCIAL_RESPONSE_CAPTURE_FAILED"
    assert result.retryable is False
    assert captured is None
    assert "private upstream detail" not in result.message
    assert response.closed is True
    assert session.closed is True
    assert len(releases) == 1
