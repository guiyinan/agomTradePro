"""TDD contracts for byte-preserving financial response capture."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import cast

import pytest

from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    raw_body_sha256,
)
from apps.data_center.infrastructure.financial_response_capture import (
    FinancialResponseCaptureError,
    capture_financial_response,
    decode_json_bytes,
)

BODY = b'{"rows":[{"REPORT_DATE":"2026-06-30","value":"1"}]}'
COMPLETED_AT = datetime(2026, 9, 14, 8, 30, 0, 123456, tzinfo=UTC)


def test_capture_retains_exact_body_after_mutable_payload_changes() -> None:
    """The response original survives parsing independently of mutable output."""

    body = b'{ "rows": [ {"value": "1"} ] }\n'
    response = _Response(body=body, headers={"Content-Length": str(len(body))})
    parser_body: list[bytes] = []

    def decode(raw: bytes) -> dict[str, list[str]]:
        """Return a mutable projection while recording the actual parser input."""

        parser_body.append(raw)
        return {"values": ["1"]}

    captured = capture_financial_response(
        response,
        request_scope=_request_scope(),
        response_scope=_response_scope(),
        decode=decode,
        clock=lambda: COMPLETED_AT,
        max_bytes=1024,
    )
    captured.payload["values"].append("changed")

    assert response.reads == 1
    assert captured.raw_body is parser_body[0]
    assert captured.raw_body == body
    assert raw_body_sha256(captured.raw_body) == captured.evidence.body_sha256
    assert len(captured.raw_body) == captured.evidence.body_size_bytes


@dataclass
class _Response:
    """Small injected response double with observable single-read behavior."""

    body: bytes = BODY
    status_code: int = 200
    headers: dict[str, str] | None = None
    encoding: str | None = "utf-8"
    reads: int = 0

    def iter_content(self, *, chunk_size: int) -> Iterator[bytes]:
        """Yield the body once, as a real streamed response would."""

        del chunk_size
        self.reads += 1
        yield self.body


def _request_scope() -> FinancialRequestScope:
    """Build a scope with only stable non-secret dimensions."""

    return FinancialRequestScope(
        provider_name="eastmoney",
        dataset_key="financial.statement",
        asset_code="000001.SZ",
        period_limit=1,
    )


def _response_scope() -> FinancialResponseScope:
    """Describe the observed response without inventing source identity."""

    return FinancialResponseScope(
        asset_codes=("000001.SZ",),
        period_ends=(date(2026, 6, 30),),
        row_count=1,
    )


def _valid_evidence() -> FinancialResponseEvidence:
    """Build one valid evidence value for focused validation cases."""

    return FinancialResponseEvidence(
        body_sha256=raw_body_sha256(BODY),
        body_size_bytes=len(BODY),
        response_completed_at=COMPLETED_AT,
        request_scope=_request_scope(),
        response_scope=_response_scope(),
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("provider_name", ""),
        ("dataset_key", " padded"),
        ("asset_code", "x" * 65),
        ("provider_name", "bad\nname"),
        ("period_limit", 0),
        ("period_limit", True),
    ],
)
def test_request_scope_rejects_untrusted_dimensions(field_name: str, value: object) -> None:
    """Scope construction cannot silently accept malformed request metadata."""

    values: dict[str, object] = {
        "provider_name": "eastmoney",
        "dataset_key": "financial.statement",
        "asset_code": "000001.SZ",
        "period_limit": 1,
    }
    values[field_name] = value

    with pytest.raises(ValueError):
        FinancialRequestScope(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "values",
    [
        {"asset_codes": ["000001.SZ"], "period_ends": (), "row_count": 1},
        {"asset_codes": (), "period_ends": (), "row_count": 1},
        {"asset_codes": ("000001.SZ", "000001.SZ"), "period_ends": (), "row_count": 1},
        {"asset_codes": (" padded",), "period_ends": (), "row_count": 1},
        {"asset_codes": (), "period_ends": (), "row_count": -1},
        {"asset_codes": (), "period_ends": (), "row_count": True},
        {"asset_codes": (), "period_ends": (datetime(2026, 6, 30, tzinfo=UTC),), "row_count": 0},
    ],
)
def test_response_scope_rejects_ambiguous_coverage(values: dict[str, object]) -> None:
    """Response scope must describe typed observations rather than coerced values."""

    with pytest.raises(ValueError):
        FinancialResponseScope(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("body_sha256", "not-a-digest"),
        ("body_size_bytes", True),
        ("body_size_bytes", -1),
        ("response_completed_at", "2026-09-14T08:30:00Z"),
        ("response_completed_at", datetime(2026, 9, 14, 8, 30)),
        (
            "response_completed_at",
            datetime(2026, 9, 14, 16, 30, tzinfo=timezone(timedelta(hours=8))),
        ),
        ("request_scope", None),
        ("response_scope", None),
        ("body_scope", "batch_response_body"),
    ],
)
def test_response_evidence_rejects_untyped_or_unverified_fields(
    field_name: str, value: object
) -> None:
    """Transport evidence cannot be assembled from coercions or local time."""

    with pytest.raises(ValueError):
        replace(_valid_evidence(), **{field_name: value})  # type: ignore[arg-type]


def test_raw_body_hash_requires_exact_bytes() -> None:
    """A text or mutable buffer cannot be presented as the immutable body."""

    with pytest.raises(ValueError):
        raw_body_sha256(cast(bytes, bytearray(BODY)))


def test_capture_hashes_exact_bytes_before_decoding() -> None:
    """The parser receives the one body whose hash is retained as evidence."""

    response = _Response(headers={"Content-Length": str(len(BODY))})
    parser_body: list[bytes] = []

    captured = capture_financial_response(
        response,
        request_scope=_request_scope(),
        response_scope=_response_scope(),
        body_scope=FinancialResponseBodyScope.BATCH,
        decode=lambda body: parser_body.append(body) or decode_json_bytes(body),
        clock=lambda: COMPLETED_AT,
        max_bytes=1024,
    )

    assert response.reads == 1
    assert parser_body == [BODY]
    assert captured.payload == {"rows": [{"REPORT_DATE": "2026-06-30", "value": "1"}]}
    assert captured.evidence.body_sha256 == raw_body_sha256(BODY)
    assert captured.evidence.body_size_bytes == len(BODY)
    assert captured.evidence.response_completed_at == COMPLETED_AT
    assert captured.evidence.body_scope is FinancialResponseBodyScope.BATCH


def test_capture_hash_is_not_a_json_reserialization_hash() -> None:
    """Whitespace and ordering in the vendor bytes remain part of the digest."""

    body = b'{ "b": 2, "a": 1 }'
    response = _Response(body=body, headers={"Content-Length": str(len(body))})
    captured = capture_financial_response(
        response,
        request_scope=_request_scope(),
        response_scope=_response_scope(),
        decode=lambda payload: payload,
        clock=lambda: COMPLETED_AT,
        max_bytes=1024,
    )

    assert captured.evidence.body_sha256 == raw_body_sha256(body)
    assert captured.evidence.body_sha256 != raw_body_sha256(b'{"a":1,"b":2}')


@pytest.mark.parametrize("status_code", [301, 400, 500])
def test_non_success_response_is_not_read_or_accepted(status_code: int) -> None:
    """HTTP failures do not create a body witness, even if a body exists."""

    response = _Response(status_code=status_code, headers={"Content-Length": "1"})

    with pytest.raises(FinancialResponseCaptureError) as caught:
        capture_financial_response(
            response,
            request_scope=_request_scope(),
            response_scope=_response_scope(),
            decode=lambda _payload: pytest.fail("failed response must not be decoded"),
            clock=lambda: COMPLETED_AT,
            max_bytes=1024,
        )

    assert caught.value.code == "FINANCIAL_RESPONSE_HTTP_ERROR"
    assert response.reads == 0


def test_declared_oversize_response_is_rejected_before_read() -> None:
    """A trusted oversized length header fails closed without consuming bytes."""

    response = _Response(body=b"x", headers={"Content-Length": "1025"})

    with pytest.raises(FinancialResponseCaptureError) as caught:
        capture_financial_response(
            response,
            request_scope=_request_scope(),
            response_scope=_response_scope(),
            decode=lambda payload: payload,
            clock=lambda: COMPLETED_AT,
            max_bytes=1024,
        )

    assert caught.value.code == "FINANCIAL_RESPONSE_TOO_LARGE"
    assert response.reads == 0


def test_streamed_oversize_response_has_no_success_evidence() -> None:
    """The actual streamed size, rather than a missing header, is bounded."""

    response = _Response(body=b"x" * 17, headers={})

    with pytest.raises(FinancialResponseCaptureError) as caught:
        capture_financial_response(
            response,
            request_scope=_request_scope(),
            response_scope=_response_scope(),
            decode=lambda payload: payload,
            clock=lambda: COMPLETED_AT,
            max_bytes=16,
        )

    assert caught.value.code == "FINANCIAL_RESPONSE_TOO_LARGE"
    assert response.reads == 1


def test_declared_short_body_is_rejected_as_truncated() -> None:
    """A valid but incomplete Content-Length cannot produce evidence."""

    response = _Response(body=BODY, headers={"Content-Length": str(len(BODY) + 1)})

    with pytest.raises(FinancialResponseCaptureError) as caught:
        capture_financial_response(
            response,
            request_scope=_request_scope(),
            response_scope=_response_scope(),
            decode=lambda payload: payload,
            clock=lambda: COMPLETED_AT,
            max_bytes=1024,
        )

    assert caught.value.code == "FINANCIAL_RESPONSE_TRUNCATED"
    assert response.reads == 1


def test_decode_failure_has_no_success_evidence() -> None:
    """Invalid JSON/parser output cannot be reported as a captured response."""

    response = _Response(headers={"Content-Length": str(len(BODY))})

    def decode(_payload: bytes) -> object:
        """Simulate the parser rejecting malformed provider data."""

        raise ValueError("parser detail must not escape")

    with pytest.raises(FinancialResponseCaptureError) as caught:
        capture_financial_response(
            response,
            request_scope=_request_scope(),
            response_scope=_response_scope(),
            decode=decode,
            clock=lambda: COMPLETED_AT,
            max_bytes=1024,
        )

    assert caught.value.code == "FINANCIAL_RESPONSE_DECODE_FAILED"
    assert "parser detail" not in str(caught.value)


@pytest.mark.parametrize(
    "body",
    [
        b'{"value": NaN}',
        b'{"value": Infinity}',
        b'{"value": -Infinity}',
        b'{"value": 1, "value": 2}',
        b'{"rows": [',
    ],
    ids=["nan", "infinity", "negative-infinity", "duplicate-key", "truncated"],
)
def test_strict_json_decoder_rejects_ambiguous_or_truncated_body(body: bytes) -> None:
    """A permissive JSON interpretation cannot create successful evidence."""

    response = _Response(body=body, headers={"Content-Length": str(len(body))})

    with pytest.raises(FinancialResponseCaptureError) as caught:
        capture_financial_response(
            response,
            request_scope=_request_scope(),
            response_scope=_response_scope(),
            decode=decode_json_bytes,
            clock=lambda: COMPLETED_AT,
            max_bytes=1024,
        )

    assert caught.value.code == "FINANCIAL_RESPONSE_DECODE_FAILED"
    assert response.reads == 1


def test_strict_json_decoder_preserves_finite_exponent_literals() -> None:
    """JSON boundary parsing does not coerce large or tiny decimals to floats."""

    decoded = decode_json_bytes(b'{"large":1e400,"small":1e-400,"tie":12.03125}')

    assert decoded == {
        "large": Decimal("1e400"),
        "small": Decimal("1e-400"),
        "tie": Decimal("12.03125"),
    }


def test_completion_must_be_aware_utc() -> None:
    """A local or naive clock cannot become transport completion evidence."""

    response = _Response(headers={"Content-Length": str(len(BODY))})

    with pytest.raises(FinancialResponseCaptureError) as caught:
        capture_financial_response(
            response,
            request_scope=_request_scope(),
            response_scope=_response_scope(),
            decode=lambda payload: payload,
            clock=lambda: datetime(2026, 9, 14, 8, 30),
            max_bytes=1024,
        )

    assert caught.value.code == "FINANCIAL_RESPONSE_COMPLETION_INVALID"


def test_scopes_are_explicit_and_never_serialize_transport_headers() -> None:
    """Evidence projections contain typed scope only, never headers or credentials."""

    response = _Response(
        headers={
            "Content-Length": str(len(BODY)),
            "Authorization": "Bearer secret-value",
        }
    )
    captured = capture_financial_response(
        response,
        request_scope=_request_scope(),
        response_scope=_response_scope(),
        decode=lambda payload: payload,
        clock=lambda: COMPLETED_AT,
        max_bytes=1024,
    )

    projection = captured.evidence.to_dict()
    assert projection["request_scope"] == {
        "provider_name": "eastmoney",
        "dataset_key": "financial.statement",
        "asset_code": "000001.SZ",
        "period_limit": 1,
    }
    assert projection["response_scope"] == {
        "asset_codes": ["000001.SZ"],
        "period_ends": ["2026-06-30"],
        "row_count": 1,
    }
    assert projection["response_scope_basis"] == "caller_declared"
    assert "Authorization" not in str(projection)
    assert "secret-value" not in str(projection)
    assert "target_url" not in projection


def test_date_only_source_remains_outside_response_evidence() -> None:
    """A response completion witness does not invent ANN or availability times."""

    response = _Response(headers={"Content-Length": str(len(BODY))})
    captured = capture_financial_response(
        response,
        request_scope=_request_scope(),
        response_scope=_response_scope(),
        decode=lambda payload: payload,
        clock=lambda: COMPLETED_AT,
        max_bytes=1024,
    )

    projection = captured.evidence.to_dict()
    assert "announced_at" not in projection
    assert "available_at" not in projection
    assert projection["response_completed_at"] == COMPLETED_AT.isoformat()


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_non_identity_content_encoding_is_rejected_before_read(encoding: str) -> None:
    """Compressed iterators cannot be bound to a wire Content-Length digest."""

    response = _Response(
        headers={
            "cOnTeNt-LeNgTh": str(len(BODY)),
            "cOnTeNt-EnCoDiNg": encoding,
        }
    )

    with pytest.raises(FinancialResponseCaptureError) as caught:
        capture_financial_response(
            response,
            request_scope=_request_scope(),
            response_scope=_response_scope(),
            decode=decode_json_bytes,
            clock=lambda: COMPLETED_AT,
            max_bytes=1024,
        )

    assert caught.value.code == "FINANCIAL_RESPONSE_ENCODING_UNSUPPORTED"
    assert response.reads == 0


def test_identity_content_encoding_uses_case_insensitive_length() -> None:
    """Identity responses retain their exact bytes with mixed-case headers."""

    response = _Response(
        headers={
            "cOnTeNt-LeNgTh": str(len(BODY)),
            "cOnTeNt-EnCoDiNg": "identity",
        }
    )

    captured = capture_financial_response(
        response,
        request_scope=_request_scope(),
        response_scope=_response_scope(),
        decode=decode_json_bytes,
        clock=lambda: COMPLETED_AT,
        max_bytes=1024,
    )

    assert captured.evidence.body_size_bytes == len(BODY)
    assert response.reads == 1


@pytest.mark.parametrize("declared", ["", "-1", "not-a-length", "１２"])
def test_invalid_content_length_is_rejected_before_read(declared: str) -> None:
    """An unverifiable length cannot support a truncation claim."""

    response = _Response(body=BODY, headers={"Content-Length": declared})

    with pytest.raises(FinancialResponseCaptureError) as caught:
        capture_financial_response(
            response,
            request_scope=_request_scope(),
            response_scope=_response_scope(),
            decode=decode_json_bytes,
            clock=lambda: COMPLETED_AT,
            max_bytes=1024,
        )

    assert caught.value.code == "FINANCIAL_RESPONSE_HEADER_INVALID"
    assert response.reads == 0


def test_conflicting_case_insensitive_content_lengths_are_rejected() -> None:
    """Two differently-cased length headers cannot be reconciled safely."""

    response = _Response(
        body=BODY,
        headers={
            "Content-Length": str(len(BODY)),
            "content-length": str(len(BODY) + 1),
        },
    )

    with pytest.raises(FinancialResponseCaptureError) as caught:
        capture_financial_response(
            response,
            request_scope=_request_scope(),
            response_scope=_response_scope(),
            decode=decode_json_bytes,
            clock=lambda: COMPLETED_AT,
            max_bytes=1024,
        )

    assert caught.value.code == "FINANCIAL_RESPONSE_HEADER_INVALID"
    assert response.reads == 0


def test_completion_is_sampled_at_stream_eof_before_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hash CPU time cannot be reported as the response completion instant."""

    events: list[str] = []
    response = _Response(headers={"Content-Length": str(len(BODY))})
    original_hash = raw_body_sha256

    def mark_hash(body: bytes) -> str:
        """Record the hash boundary after the completion clock."""

        events.append("hash")
        return original_hash(body)

    def mark_clock() -> datetime:
        """Record the completion clock boundary."""

        events.append("clock")
        return COMPLETED_AT

    original_iter_content = response.iter_content

    def mark_read(*, chunk_size: int) -> Iterator[bytes]:
        """Record the end-of-stream before returning the chunk."""

        yield from original_iter_content(chunk_size=chunk_size)
        events.append("eof")

    monkeypatch.setattr(response, "iter_content", mark_read)
    monkeypatch.setattr(
        "apps.data_center.infrastructure.financial_response_capture.raw_body_sha256",
        mark_hash,
    )

    capture_financial_response(
        response,
        request_scope=_request_scope(),
        response_scope=_response_scope(),
        decode=decode_json_bytes,
        clock=mark_clock,
        max_bytes=1024,
    )

    assert events == ["eof", "clock", "hash"]
