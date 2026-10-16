"""Opt-in exact non-financial response capture at Tushare HTTP boundaries."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast
from uuid import uuid4

import pytest

from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure import egress_transport as egress_transport_module
from apps.data_center.infrastructure import tushare_client
from core.exceptions import TushareError


class _RawStream:
    """Minimal urllib3-like raw stream yielding the exact entity bytes."""

    def __init__(self, body: bytes, *, fail: bool = False) -> None:
        self.body = body
        self.fail = fail
        self.calls = 0

    def stream(self, amt: int, decode_content: bool = False) -> Iterator[bytes]:
        """Yield chunks without transparent content decoding."""

        assert decode_content is False
        self.calls += 1
        if self.fail:
            raise OSError("private stream detail")
        for offset in range(0, len(self.body), amt):
            yield self.body[offset : offset + amt]


class _Response:
    """HTTP response double supporting raw bytes and cleanup checks."""

    status_code = 200
    is_redirect = False
    is_permanent_redirect = False

    def __init__(self, body: bytes, *, headers: Mapping[str, str] | None = None) -> None:
        self.body = body
        self.headers = dict(
            headers
            or {
                "Content-Length": str(len(body)),
                "Content-Type": "application/json; charset=utf-8",
                "Content-Encoding": "identity",
            }
        )
        self.raw = _RawStream(body)
        self.closed = False

    def close(self) -> None:
        """Record that the response was released after capture."""

        self.closed = True


class _Repository:
    """Immutable RawPayload test repository matching the public use-case port."""

    def __init__(self) -> None:
        self.rows: dict[str, RawPayload] = {}

    def save(self, payload: RawPayload) -> RawPayload:
        """Persist an exact replay or reject a conflicting immutable identity."""

        existing = self.rows.get(payload.payload_hash)
        if existing is not None and existing != payload:
            raise ValueError("raw_payload_immutable_conflict")
        self.rows[payload.payload_hash] = payload
        return payload


class _Session:
    """Fake session whose only network operation returns an injected response."""

    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []
        self.headers: dict[str, str] = {"X-API-Key": "tok-secret"}
        self.trust_env = False
        self.proxies: dict[str, str] = {}
        self.closed = False

    def mount(self, _scheme: str, _adapter: object) -> None:
        """Accept a transport adapter without performing network I/O."""

    def close(self) -> None:
        """Record session cleanup."""

        self.closed = True

    def post(self, _url: str, **kwargs: object) -> _Response:
        """Capture one direct POST invocation without network access."""

        self.calls.append(kwargs)
        return self.response

    def get(self, _url: str, **kwargs: object) -> _Response:
        """Capture one direct GET invocation without network access."""

        self.calls.append(kwargs)
        return self.response


def _valid_provider_body(message: str = "ok") -> bytes:
    """Return one complete Tushare table envelope with stable JSON bytes."""

    return (
        '{"code":0,"message":'
        + json.dumps(message)
        + ',"data":{"fields":["ts_code","close"],"items":[["000001.SZ",1.25]]}}'
    ).encode("utf-8")


def _install_direct_client(
    monkeypatch: pytest.MonkeyPatch,
    response: _Response,
    repository: _Repository,
) -> tuple[tushare_client._UnifiedRelayClient, _Session]:
    """Compose an opt-in direct Tushare client and real RawPayload use case."""

    session = _Session(response)
    client = tushare_client._UnifiedRelayClient(
        token="tok-secret",
        http_url="https://url-user:url-pass@market.example.com/pro?token=query-secret",
        dataset_key="equity.reference",
        provider_response_handler=lambda capture, **kwargs: RetainProviderResponsePayloadUseCase(
            repository
        ).execute(capture, **kwargs),
    )
    client._session = cast(object, session)
    session.headers["Authorization"] = "Bearer header-secret"
    monkeypatch.setattr(client, "_should_use_egress", lambda *_args, **_kwargs: False)
    return client, session


def test_direct_opt_in_retains_exact_body_and_serializable_reference(monkeypatch) -> None:
    """Validated HTTP bytes, not reserialized DataFrame rows, anchor the reference."""

    body = _valid_provider_body()
    response = _Response(body)
    repository = _Repository()
    client, session = _install_direct_client(monkeypatch, response, repository)

    frame = client.query("stock_basic", fields="ts_code,close")

    assert isinstance(frame, tushare_client._WitnessedProviderFrame)
    evidence = frame.response_evidence
    reference = evidence.raw_payload_reference
    assert reference is not None
    assert reference.transport is ProviderResponseTransport.DIRECT
    assert reference.body_sha256 == sha256(body).hexdigest()
    assert reference.original_body_retained is True
    assert evidence.response_completed_at == reference.response_completed_at
    assert session.calls[0]["headers"] == {"Accept-Encoding": "identity"}
    assert session.calls[0]["stream"] is True
    assert response.raw.calls == 1
    assert response.closed is True
    row = repository.rows[reference.payload_hash]
    assert reference.verifies(row)
    assert row.payload["retained_response_json"] == body.decode("utf-8")
    serialized = json.loads(json.dumps(frame.response_evidence.to_payload()))
    rebuilt = ProviderResponsePayloadReference.from_payload(
        cast(Mapping[str, object], serialized["raw_payload_reference"])
    )
    assert rebuilt.verifies(row)


def test_capture_redacts_echoed_url_header_and_token_credentials(monkeypatch) -> None:
    """Credentials in response text are scrubbed and originals are not retained."""

    message = "tok-secret url-user url-pass query-secret header-secret"
    body = _valid_provider_body(message)
    repository = _Repository()
    client, _session = _install_direct_client(monkeypatch, _Response(body), repository)

    frame = client.query("stock_basic", fields="ts_code,close")

    reference = frame.response_evidence.raw_payload_reference
    assert reference is not None
    assert reference.original_body_retained is False
    row = repository.rows[reference.payload_hash]
    retained = row.payload["retained_response_json"]
    assert isinstance(retained, str)
    for secret in ("tok-secret", "url-user", "url-pass", "query-secret", "header-secret"):
        assert secret not in retained
    assert "[REDACTED]" in retained
    assert reference.body_sha256 != reference.retained_content_sha256
    assert reference.verifies(row)


def test_tushare_egress_capture_uses_same_reference_contract(monkeypatch) -> None:
    """The routed path retains the same exact capture DTO after table validation."""

    from apps.data_center.application import egress_service

    body = _valid_provider_body()
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=datetime(2026, 10, 16, 4, 0, tzinfo=UTC),
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.EGRESS,
    )
    repository = _Repository()
    client = tushare_client._UnifiedRelayClient(
        token="tok-secret",
        http_url="https://market.example.com/pro",
        provider_id=7,
        dataset_key="equity.reference",
        provider_response_handler=lambda response_capture, **kwargs: RetainProviderResponsePayloadUseCase(
            repository
        ).execute(
            response_capture, **kwargs
        ),
    )
    monkeypatch.setattr(client, "_should_use_egress", lambda *_args, **_kwargs: True)

    def execute(*_args: object, **_kwargs: object) -> ProviderResponseCapture:
        return capture

    monkeypatch.setattr(egress_service, "execute_provider_response_request", execute)

    frame = client.query("stock_basic", fields="ts_code,close")

    reference = frame.response_evidence.raw_payload_reference
    assert reference is not None
    assert reference.transport is ProviderResponseTransport.EGRESS
    row = repository.rows[reference.payload_hash]
    assert reference.verifies(row)


def test_native_sdk_opt_in_fails_before_calling_unwitnessed_sdk(monkeypatch) -> None:
    """A native SDK DataFrame cannot be relabeled as an exact HTTP capture."""

    from unittest.mock import Mock

    sdk_client = Mock()
    client = tushare_client._RoutedSdkClient(
        sdk_client=sdk_client,
        token="tok-secret",
        http_url="https://market.example.com/pro",
        provider_id=7,
        deployment_region="test",
        dataset_key="equity.reference",
        provider_response_handler=lambda *_args, **_kwargs: cast(
            ProviderResponsePayloadReference, object()
        ),
    )
    monkeypatch.setattr(client, "_should_use_egress", lambda *_args, **_kwargs: False)

    with pytest.raises(TushareError) as caught:
        client.query("stock_basic", ts_code="000001.SZ")

    assert caught.value.code == "TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNAVAILABLE"
    sdk_client.query.assert_not_called()


@pytest.mark.parametrize(
    ("body", "headers", "expected_code"),
    [
        (_valid_provider_body(), {"Content-Length": "1"}, "PROVIDER_RESPONSE_BODY_TRUNCATED"),
        (b'{"code":0,"data":', {}, "PROVIDER_RESPONSE_JSON_INVALID"),
        (
            b'{"code":0,"data":{"fields":[],"items":[]}}',
            {"Content-Encoding": "gzip"},
            "PROVIDER_RESPONSE_ENCODING_UNSUPPORTED",
        ),
        (
            b'{"code":9,"data":{"fields":[],"items":[]}}',
            {},
            "TUSHARE_PROVIDER_REJECTED",
        ),
    ],
)
def test_invalid_provider_response_never_invokes_retention_handler(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    headers: Mapping[str, str],
    expected_code: str,
) -> None:
    """Bad JSON, truncation, encoding, and provider rejection have no artifact."""

    response = _Response(body, headers=headers)
    repository = _Repository()
    client, _session = _install_direct_client(monkeypatch, response, repository)

    with pytest.raises(TushareError) as caught:
        client.query("stock_basic", fields="ts_code")

    assert caught.value.code == expected_code
    assert repository.rows == {}
    assert response.closed is True


def test_egress_transport_returns_exact_capture_only_for_valid_json(monkeypatch) -> None:
    """Governed egress uses one raw stream and never builds evidence from a frame."""

    body = _valid_provider_body()
    response = _Response(body)
    session = _Session(response)
    releases: list[str] = []
    prepared = type(
        "PreparedTarget",
        (),
        {
            "scheme": "https",
            "host_header": "market.example.com",
            "adapter": object(),
            "url": "https://market.example.com/pro",
        },
    )()
    monkeypatch.setattr(egress_transport_module.requests, "Session", lambda: session)
    monkeypatch.setattr(egress_transport_module, "_validate_public_target", lambda _url: prepared)
    monkeypatch.setattr(egress_transport_module._shared_state, "circuit_open", lambda _key: False)
    monkeypatch.setattr(
        egress_transport_module._shared_state, "shared_state_unavailable", lambda: False
    )
    monkeypatch.setattr(
        egress_transport_module._shared_state, "acquire", lambda *_args, **_kwargs: True
    )
    monkeypatch.setattr(
        egress_transport_module._shared_state, "release", lambda key: releases.append(key)
    )
    monkeypatch.setattr(egress_transport_module._shared_state, "success", lambda _key: None)

    transport = egress_transport_module.EgressHttpTransport(max_attempts=1)
    result, capture = transport.request_provider_response(
        EgressRequestContext(
            provider_id=7,
            dataset_key="equity.reference",
            target_url="https://market.example.com/pro",
            deployment_region="test",
        ),
        egress_id=None,
        request_id=uuid4(),
        attempt=1,
        method="POST",
        params=None,
        json_body={"api_name": "stock_basic"},
        headers={"X-API-Key": "tok-secret"},
    )

    assert result.outcome == "success"
    assert isinstance(capture, ProviderResponseCapture)
    assert capture.transport is ProviderResponseTransport.EGRESS
    assert capture.body_sha256 == sha256(body).hexdigest()
    assert session.calls[0]["headers"]["Accept-Encoding"] == "identity"
    assert response.raw.calls == 1 and response.closed and session.closed
    assert len(releases) == 1


def test_egress_non_identity_request_is_blocked_before_http(monkeypatch) -> None:
    """The capture mode never silently overrides caller compression settings."""

    response = _Response(b'{"code":0}')
    session = _Session(response)
    monkeypatch.setattr(egress_transport_module.requests, "Session", lambda: session)
    transport = egress_transport_module.EgressHttpTransport(max_attempts=1)

    result, capture = transport.request_provider_response(
        EgressRequestContext(
            provider_id=7,
            dataset_key="equity.reference",
            target_url="https://market.example.com/pro",
            deployment_region="test",
        ),
        egress_id=None,
        request_id=uuid4(),
        attempt=1,
        method="GET",
        params=None,
        json_body=None,
        headers={"accept-encoding": "gzip"},
    )

    assert result.outcome == "blocked"
    assert result.error_code == "EGRESS_PROVIDER_RESPONSE_ENCODING_UNSUPPORTED"
    assert capture is None
    assert session.calls == []
