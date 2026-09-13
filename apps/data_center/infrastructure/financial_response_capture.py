"""Injectable, byte-preserving capture for one provider response.

This seam deliberately does not create an HTTP session or choose an egress
route.  A caller injects the already-routed response object and a parser.  It
accepts only identity or unspecified content encoding because requests-style
stream iterators may transparently decompress other encodings.  It reads the
application body once, records completion at stream EOF, hashes those exact
bytes, and then gives the same bytes to the parser.  Existing JSON-only
egress contracts remain unchanged until a provider explicitly adopts this
seam.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Generic, NoReturn, Protocol, TypeVar, cast

from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    raw_body_sha256,
)
from core.exceptions import DataFetchError

PayloadT = TypeVar("PayloadT")
PayloadT_co = TypeVar("PayloadT_co", covariant=True)


class FinancialResponseCaptureError(DataFetchError):
    """Raised when a response cannot produce trusted raw-body evidence."""

    default_message = "金融响应证据捕获失败。"
    default_code = "FINANCIAL_RESPONSE_CAPTURE_FAILED"


class RawFinancialResponseProtocol(Protocol):
    """Minimal response boundary required by the injectable capture seam."""

    status_code: int
    headers: Mapping[str, str]

    def iter_content(self, *, chunk_size: int) -> Iterable[bytes]:
        """Yield unencoded response body chunks without exposing headers."""
        ...


class FinancialResponseDecoder(Protocol[PayloadT_co]):
    """Decode one exact response buffer without reserializing it."""

    def __call__(self, body: bytes) -> PayloadT_co:
        """Parse the captured bytes into a provider-specific payload."""
        ...


class UtcClock(Protocol):
    """Clock port used to make completion timing deterministic in tests."""

    def __call__(self) -> datetime:
        """Return the current aware UTC time."""
        ...


def _utc_now() -> datetime:
    """Return the system's current aware UTC time for completion evidence."""

    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CapturedFinancialResponse(Generic[PayloadT]):
    """Parsed payload paired with evidence for the exact response bytes."""

    payload: PayloadT
    evidence: FinancialResponseEvidence


def capture_financial_response(
    response: RawFinancialResponseProtocol,
    *,
    request_scope: FinancialRequestScope,
    response_scope: FinancialResponseScope,
    decode: FinancialResponseDecoder[PayloadT],
    body_scope: FinancialResponseBodyScope = FinancialResponseBodyScope.BATCH,
    clock: UtcClock = _utc_now,
    max_bytes: int = 4 * 1024 * 1024,
) -> CapturedFinancialResponse[PayloadT]:
    """Capture, hash, timestamp, and parse one bounded successful response.

    The status, encoding, and declared size are checked before reading.  The
    body is consumed exactly once; the completion clock is sampled at stream
    EOF, then its digest and byte count are computed, and the same immutable
    buffer is passed to ``decode``.  Decode or stream failures raise a
    sanitized DataFetchError and return no accepted evidence.
    """

    _validate_capture_configuration(max_bytes)
    _validate_success_status(response.status_code)
    _reject_non_identity_encoding(response.headers)
    declared_size = _declared_content_length(response.headers)
    if declared_size is not None and declared_size > max_bytes:
        raise FinancialResponseCaptureError(
            "金融响应超过大小上限。", code="FINANCIAL_RESPONSE_TOO_LARGE"
        )
    body, response_completed_at = _read_body_once(response, max_bytes, declared_size, clock)
    body_size_bytes = len(body)
    body_sha256 = raw_body_sha256(body)
    try:
        evidence = FinancialResponseEvidence(
            body_sha256=body_sha256,
            body_size_bytes=body_size_bytes,
            response_completed_at=response_completed_at,
            request_scope=request_scope,
            response_scope=response_scope,
            body_scope=body_scope,
        )
    except FinancialResponseCaptureError:
        raise
    except Exception as exc:
        raise FinancialResponseCaptureError(
            "金融响应完成时间无效。", code="FINANCIAL_RESPONSE_COMPLETION_INVALID"
        ) from exc
    try:
        payload = decode(body)
    except Exception as exc:
        raise FinancialResponseCaptureError(
            "金融响应内容无法解析。", code="FINANCIAL_RESPONSE_DECODE_FAILED"
        ) from exc
    return CapturedFinancialResponse(payload=payload, evidence=evidence)


def decode_json_bytes(body: bytes) -> object:
    """Decode one UTF-8 buffer while rejecting ambiguous JSON responses.

    Duplicate object keys and non-standard numeric constants are rejected so
    a successful capture cannot depend on the permissive defaults of
    ``json.loads``.  Decimal parsing preserves finite exponent literals such
    as ``1e400`` until a provider-specific parser narrows them.  The returned
    value remains at the JSON boundary as an ``object``.
    """

    if not isinstance(body, bytes):
        raise ValueError("financial response body must be bytes")
    try:
        text = body.decode("utf-8")
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
            parse_float=Decimal,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("financial response JSON is invalid") from exc
    return cast(object, decoded)


def _validate_capture_configuration(max_bytes: int) -> None:
    """Reject an invalid response ceiling before touching the injected body."""

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise FinancialResponseCaptureError(
            "金融响应大小上限无效。", code="FINANCIAL_RESPONSE_CONFIG_INVALID"
        )


def _validate_success_status(status_code: object) -> None:
    """Reject HTTP failures without reading or retaining their response body."""

    if isinstance(status_code, bool) or not isinstance(status_code, int):
        raise FinancialResponseCaptureError(
            "金融响应状态码无效。", code="FINANCIAL_RESPONSE_HTTP_ERROR"
        )
    if not 200 <= status_code < 300:
        raise FinancialResponseCaptureError(
            "金融响应状态码未成功。", code="FINANCIAL_RESPONSE_HTTP_ERROR"
        )


def _declared_content_length(headers: Mapping[str, str]) -> int | None:
    """Return one valid Content-Length or reject an unverifiable header."""

    values = _header_values(headers, "Content-Length")
    if not values:
        return None
    if len(values) != 1:
        raise FinancialResponseCaptureError(
            "金融响应长度头不明确。", code="FINANCIAL_RESPONSE_HEADER_INVALID"
        )
    declared = values[0].strip()
    if not declared or not declared.isascii() or not declared.isdecimal():
        raise FinancialResponseCaptureError(
            "金融响应长度头无效。", code="FINANCIAL_RESPONSE_HEADER_INVALID"
        )
    return int(declared)


def _reject_non_identity_encoding(headers: Mapping[str, str]) -> None:
    """Reject transparent compression before Content-Length can be misbound."""

    values = _header_values(headers, "Content-Encoding")
    if len(values) > 1:
        raise FinancialResponseCaptureError(
            "金融响应编码头不明确。", code="FINANCIAL_RESPONSE_HEADER_INVALID"
        )
    content_encoding = values[0] if values else None
    if content_encoding is not None and content_encoding.strip().lower() not in {"", "identity"}:
        raise FinancialResponseCaptureError(
            "金融响应编码无法作为原始字节证据。",
            code="FINANCIAL_RESPONSE_ENCODING_UNSUPPORTED",
        )


def _header_values(headers: Mapping[str, str], name: str) -> tuple[str, ...]:
    """Read one HTTP header case-insensitively without retaining the mapping."""

    wanted = name.lower()
    values: list[str] = []
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == wanted:
            if not isinstance(value, str):
                raise FinancialResponseCaptureError(
                    "金融响应头类型无效。", code="FINANCIAL_RESPONSE_HEADER_INVALID"
                )
            values.append(value)
    return tuple(values)


def _read_body_once(
    response: RawFinancialResponseProtocol,
    max_bytes: int,
    declared_size: int | None,
    clock: UtcClock,
) -> tuple[bytes, datetime]:
    """Read one bounded body and discard no bytes to a second parser path."""

    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=16 * 1024):
            if not isinstance(chunk, bytes):
                raise FinancialResponseCaptureError(
                    "金融响应块类型无效。", code="FINANCIAL_RESPONSE_READ_FAILED"
                )
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise FinancialResponseCaptureError(
                    "金融响应超过大小上限。", code="FINANCIAL_RESPONSE_TOO_LARGE"
                )
            chunks.append(chunk)
    except FinancialResponseCaptureError:
        raise
    except Exception as exc:
        raise FinancialResponseCaptureError(
            "金融响应读取失败。", code="FINANCIAL_RESPONSE_READ_FAILED"
        ) from exc
    try:
        response_completed_at = clock()
    except Exception as exc:
        raise FinancialResponseCaptureError(
            "金融响应完成时间无效。", code="FINANCIAL_RESPONSE_COMPLETION_INVALID"
        ) from exc
    if declared_size is not None and total != declared_size:
        raise FinancialResponseCaptureError(
            "金融响应体长度不完整。", code="FINANCIAL_RESPONSE_TRUNCATED"
        )
    body = b"".join(chunks)
    return body, response_completed_at


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate object members instead of silently taking the last."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    """Reject NaN and infinities accepted by Python's permissive JSON parser."""

    del value
    raise ValueError("non-standard JSON numeric constant")


__all__ = [
    "CapturedFinancialResponse",
    "FinancialResponseCaptureError",
    "FinancialResponseDecoder",
    "RawFinancialResponseProtocol",
    "UtcClock",
    "capture_financial_response",
    "decode_json_bytes",
]
