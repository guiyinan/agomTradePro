"""Exact raw-byte capture for governed non-JSON provider documents."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from uuid import UUID

import pytest
from urllib3.exceptions import ProtocolError

from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.provider_document_response import (
    ProviderDocumentResponseCapture,
    normalize_document_content_type,
    normalize_document_media_type_allowlist,
)
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.infrastructure import provider_document_response_capture as capture_module
from apps.data_center.infrastructure.provider_document_response_capture import (
    ProviderDocumentResponseCaptureError,
    capture_provider_document_response,
)

_REQUEST_ID = UUID("6e31d311-2f53-4817-8990-f7ab3fbe8a5b")
_BODY = b"<html>legal \x00bytes\xff</html>"
_TARGET_URL = "https://laws.example.test/path?id=secret"
_CAPTURED_AT = datetime(2026, 11, 12, 4, 5, 6, tzinfo=UTC)


def _document_capture(**overrides: object) -> ProviderDocumentResponseCapture:
    """Construct a valid capture fixture whose body is deliberately not JSON."""

    values: dict[str, object] = {
        "request_id": _REQUEST_ID,
        "attempt": 1,
        "egress_id": None,
        "target_url_sha256": hashlib.sha256(_TARGET_URL.encode("utf-8")).hexdigest(),
        "target_host": "laws.example.test",
        "body": _BODY,
        "body_sha256": hashlib.sha256(_BODY).hexdigest(),
        "body_size_bytes": len(_BODY),
        "response_completed_at": _CAPTURED_AT,
        "status_code": 200,
        "content_type": "text/html; charset=utf-8",
        "transport": ProviderResponseTransport.EGRESS,
    }
    values.update(overrides)
    return ProviderDocumentResponseCapture(**values)  # type: ignore[arg-type]


class _RawStream:
    """Minimal undecoded stream that exposes whether all bytes were consumed."""

    def __init__(
        self,
        chunks: tuple[bytes, ...],
        *,
        read_raises: bool = False,
        stream_error: BaseException | None = None,
    ) -> None:
        self.chunks = chunks
        self.read_raises = read_raises
        self.stream_error = stream_error
        self.completed = False
        self.calls = 0

    def stream(self, amt: int, decode_content: bool = False):
        assert amt > 0
        assert decode_content is False
        self.calls += 1
        if self.stream_error is not None:
            raise self.stream_error
        if self.read_raises:
            raise OSError("raw stream failed")
        yield from self.chunks
        self.completed = True


class _Response:
    """Small HTTP response shape consumed by the byte capture adapter."""

    def __init__(
        self,
        body: bytes,
        *,
        content_type: str = "text/html; charset=utf-8",
        content_length: str | None = None,
        content_encoding: str | None = None,
        status_code: int = 200,
        read_raises: bool = False,
        stream_error: BaseException | None = None,
    ) -> None:
        headers = {"Content-Type": content_type}
        if content_length is not None:
            headers["Content-Length"] = content_length
        if content_encoding is not None:
            headers["Content-Encoding"] = content_encoding
        self.headers = headers
        self.status_code = status_code
        self.raw = _RawStream(
            (body[:5], body[5:]), read_raises=read_raises, stream_error=stream_error
        )


def _capture(response: _Response, *, max_bytes: int = 1024):
    """Capture one exact body for a fixed request identity and destination."""

    return capture_provider_document_response(
        response,
        request_id=_REQUEST_ID,
        attempt=1,
        egress_id=None,
        target_url=_TARGET_URL,
        transport=ProviderResponseTransport.EGRESS,
        max_bytes=max_bytes,
        allowed_media_types=frozenset({"text/html"}),
    )


class _BrokenTimezone(tzinfo):
    """Timezone whose UTC offset cannot be represented."""

    def utcoffset(self, dt: datetime | None) -> timedelta:
        del dt
        raise ValueError("broken offset")

    def dst(self, dt: datetime | None) -> timedelta | None:
        del dt
        return None

    def tzname(self, dt: datetime | None) -> str:
        del dt
        return "broken"


def test_document_capture_preserves_exact_non_json_bytes_and_completion_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw HTML bytes are retained without UTF-8 or JSON decoding."""

    response = _Response(_BODY, content_length=str(len(_BODY)))
    fixed_clock = type(
        "FixedClock",
        (),
        {
            "now": staticmethod(
                lambda tz: (
                    _CAPTURED_AT
                    if tz is UTC and response.raw.completed
                    else pytest.fail("completion clock sampled before the body was consumed")
                )
            )
        },
    )
    monkeypatch.setattr(capture_module, "datetime", fixed_clock)

    capture = _capture(response)

    assert capture.body == _BODY
    assert capture.body_sha256 == hashlib.sha256(_BODY).hexdigest()
    assert capture.body_size_bytes == len(_BODY)
    assert capture.response_completed_at == _CAPTURED_AT
    assert capture.content_type == "text/html; charset=utf-8"
    assert capture.request_id == _REQUEST_ID
    assert capture.attempt == 1
    assert capture.target_host == "laws.example.test"
    assert capture.transport is ProviderResponseTransport.EGRESS
    assert response.raw.calls == 1


def test_document_capture_accepts_identity_encoded_pdf_bytes() -> None:
    """The raw path supports PDF bytes without passing them through JSON."""

    response = _Response(b"%PDF\x00\xff", content_type="application/pdf")
    capture = capture_provider_document_response(
        response,
        request_id=_REQUEST_ID,
        attempt=2,
        egress_id=19,
        target_url=_TARGET_URL,
        transport=ProviderResponseTransport.EGRESS,
        max_bytes=1024,
        allowed_media_types=frozenset({"application/pdf"}),
    )
    assert capture.body == b"%PDF\x00\xff"
    assert capture.attempt == 2
    assert capture.egress_id == 19


@pytest.mark.parametrize(
    ("response", "max_bytes", "accepted", "error_code"),
    [
        (_Response(b""), 1024, frozenset({"text/html"}), "PROVIDER_DOCUMENT_EMPTY_BODY"),
        (
            _Response(_BODY, content_encoding="gzip"),
            1024,
            frozenset({"text/html"}),
            "PROVIDER_DOCUMENT_ENCODING_UNSUPPORTED",
        ),
        (
            _Response(_BODY, content_type="application/json"),
            1024,
            frozenset({"text/html"}),
            "PROVIDER_DOCUMENT_MEDIA_TYPE_REJECTED",
        ),
        (
            _Response(_BODY, content_length=str(len(_BODY) + 1)),
            1024,
            frozenset({"text/html"}),
            "PROVIDER_DOCUMENT_BODY_TRUNCATED",
        ),
        (
            _Response(_BODY, content_length="not-a-number"),
            1024,
            frozenset({"text/html"}),
            "PROVIDER_DOCUMENT_CONTENT_LENGTH_INVALID",
        ),
        (
            _Response(_BODY, content_length="5000"),
            1024,
            frozenset({"text/html"}),
            "PROVIDER_DOCUMENT_BODY_TOO_LARGE",
        ),
        (
            _Response(_BODY),
            5,
            frozenset({"text/html"}),
            "PROVIDER_DOCUMENT_BODY_TOO_LARGE",
        ),
        (
            _Response(_BODY, read_raises=True),
            1024,
            frozenset({"text/html"}),
            "PROVIDER_DOCUMENT_BODY_READ_FAILED",
        ),
        (
            _Response(_BODY, stream_error=ProtocolError("truncated raw stream")),
            1024,
            frozenset({"text/html"}),
            "PROVIDER_DOCUMENT_BODY_READ_FAILED",
        ),
        (
            _Response(_BODY, content_type=""),
            1024,
            frozenset({"text/html"}),
            "PROVIDER_DOCUMENT_CONTENT_TYPE_INVALID",
        ),
        (
            _Response(_BODY, status_code=302),
            1024,
            frozenset({"text/html"}),
            "PROVIDER_DOCUMENT_HTTP_FAILED",
        ),
    ],
)
def test_document_capture_rejects_invalid_response_bytes(
    response: _Response,
    max_bytes: int,
    accepted: frozenset[str],
    error_code: str,
) -> None:
    """Invalid MIME, framing, encoding, status and size never yield capture."""

    with pytest.raises(ProviderDocumentResponseCaptureError) as caught:
        capture_provider_document_response(
            response,
            request_id=_REQUEST_ID,
            attempt=1,
            egress_id=None,
            target_url=_TARGET_URL,
            transport=ProviderResponseTransport.EGRESS,
            max_bytes=max_bytes,
            allowed_media_types=accepted,
        )
    assert caught.value.code == error_code


@pytest.mark.parametrize(
    "allowed",
    [
        frozenset(),
        frozenset({"*/*"}),
        frozenset({"text/*"}),
        frozenset({"text/html; charset=utf-8"}),
    ],
)
def test_document_media_type_allowlist_requires_exact_concrete_types(
    allowed: frozenset[str],
) -> None:
    """Empty, wildcard and parameterized media types cannot widen capture."""

    with pytest.raises(ValueError):
        normalize_document_media_type_allowlist(allowed)


def test_document_media_type_allowlist_rejects_mutable_input() -> None:
    """The request contract cannot retain a caller-mutable MIME set."""

    with pytest.raises(ValueError):
        normalize_document_media_type_allowlist({"text/html"})


def test_document_media_type_normalization_ignores_parameters_only() -> None:
    """A response's raw type is preserved while matching its exact MIME essence."""

    assert normalize_document_content_type("Text/HTML; charset=UTF-8") == "text/html"


@pytest.mark.parametrize("content_type", [object(), "x" * 513, "text/html\n"])
def test_document_content_type_rejects_unbounded_or_control_input(content_type: object) -> None:
    """Content-Type metadata must be a bounded, control-free header value."""

    with pytest.raises(ValueError):
        normalize_document_content_type(content_type)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"body": b""}, "body"),
        ({"body_sha256": "0" * 64}, "body_sha256"),
        ({"body_sha256": "bad"}, "body_sha256"),
        ({"body_size_bytes": True}, "body_size_bytes"),
        ({"status_code": 302}, "status_code"),
        ({"attempt": 0}, "attempt"),
        ({"attempt": True}, "attempt"),
        ({"egress_id": True}, "egress_id"),
        ({"request_id": "not-a-uuid"}, "request_id"),
        ({"target_url_sha256": "bad"}, "target_url_sha256"),
        ({"target_host": " Laws.example.test"}, "target_host"),
        ({"response_completed_at": "not-a-datetime"}, "response_completed_at"),
        ({"response_completed_at": datetime(2026, 11, 12)}, "response_completed_at"),
        (
            {"response_completed_at": datetime(2026, 11, 12, tzinfo=timezone(timedelta(hours=1)))},
            "response_completed_at",
        ),
        (
            {"response_completed_at": datetime(2026, 11, 12, tzinfo=_BrokenTimezone())},
            "response_completed_at",
        ),
        ({"content_type": 1}, "content_type"),
        ({"transport": "egress"}, "transport"),
    ],
)
def test_document_capture_rejects_unbound_or_malformed_metadata(
    overrides: dict[str, object], message: str
) -> None:
    """The Domain capture verifies its request, destination and byte identity."""

    with pytest.raises(ValueError, match=message):
        _document_capture(**overrides)


def test_capture_application_context_is_typed() -> None:
    """The egress context owns a normalized HTTP destination before capture."""

    context = EgressRequestContext(
        provider_id=7,
        dataset_key="statutory.source",
        target_url=_TARGET_URL,
        deployment_region="default",
    )
    assert context.target_url == _TARGET_URL
