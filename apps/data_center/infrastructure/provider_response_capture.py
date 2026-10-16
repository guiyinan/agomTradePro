"""Capture exact successful non-financial provider HTTP response bodies."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Protocol

from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from core.exceptions import DataFetchError


class ProviderResponseCaptureError(DataFetchError):
    """Raised when an HTTP response cannot be represented as exact JSON bytes."""

    default_message = "Provider 响应字节无法安全捕获。"
    default_code = "PROVIDER_RESPONSE_CAPTURE_FAILED"


class _ResponseBodyStream(Protocol):
    """The requests raw stream surface needed to avoid transparent decoding."""

    def stream(self, amt: int, decode_content: bool = False) -> Iterator[bytes]:
        """Yield raw HTTP entity bytes in bounded chunks."""
        ...


class ProviderResponseHttpProtocol(Protocol):
    """Minimal successful response surface used by the exact body reader."""

    status_code: int
    headers: Mapping[str, str]
    raw: _ResponseBodyStream


def capture_provider_response_body(
    response: ProviderResponseHttpProtocol,
    *,
    transport: ProviderResponseTransport,
    max_bytes: int,
) -> ProviderResponseCapture:
    """Read an identity-encoded JSON entity once and bind its exact bytes.

    The completion timestamp is sampled locally after the full body has been
    consumed. A digest is retained for the original body; persistence later
    stores a separately hashed, redacted JSON representation.
    """

    if not isinstance(transport, ProviderResponseTransport):
        raise ProviderResponseCaptureError(
            "响应传输标记无效。", code="PROVIDER_RESPONSE_CAPTURE_INVALID"
        )
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ProviderResponseCaptureError(
            "响应大小上限无效。", code="PROVIDER_RESPONSE_CAPTURE_INVALID"
        )
    if isinstance(response.status_code, bool) or not 200 <= response.status_code < 300:
        raise ProviderResponseCaptureError(
            "Provider 响应状态不是成功。", code="PROVIDER_RESPONSE_HTTP_FAILED"
        )

    content_encoding = response.headers.get("Content-Encoding", "").strip().casefold()
    if content_encoding not in {"", "identity"}:
        raise ProviderResponseCaptureError(
            "Provider 响应使用了非 identity 编码。",
            code="PROVIDER_RESPONSE_ENCODING_UNSUPPORTED",
        )

    expected_size = _content_length(response.headers, max_bytes)
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.raw.stream(16 * 1024, decode_content=False):
            if not isinstance(chunk, bytes):
                raise ValueError("response_stream_chunk_not_bytes")
            total += len(chunk)
            if total > max_bytes:
                raise ProviderResponseCaptureError(
                    "Provider 响应超过大小上限。",
                    code="PROVIDER_RESPONSE_BODY_TOO_LARGE",
                )
            chunks.append(chunk)
    except ProviderResponseCaptureError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ProviderResponseCaptureError(
            "Provider 响应读取未完整完成。",
            code="PROVIDER_RESPONSE_BODY_READ_FAILED",
        ) from exc

    if expected_size is not None and total != expected_size:
        raise ProviderResponseCaptureError(
            "Provider 响应声明长度与已读取字节不符。",
            code="PROVIDER_RESPONSE_BODY_TRUNCATED",
        )
    body = b"".join(chunks)
    completed_at = datetime.now(UTC)
    payload = _decode_json_body(body)
    content_type = response.headers.get("Content-Type")
    try:
        return ProviderResponseCapture(
            body=body,
            payload=payload,
            body_sha256=hashlib.sha256(body).hexdigest(),
            body_size_bytes=len(body),
            response_completed_at=completed_at,
            status_code=response.status_code,
            content_type=content_type,
            transport=transport,
        )
    except ValueError as exc:
        raise ProviderResponseCaptureError(
            "Provider 响应捕获元数据无效。",
            code="PROVIDER_RESPONSE_CAPTURE_INVALID",
        ) from exc


def _content_length(headers: Mapping[str, str], max_bytes: int) -> int | None:
    """Validate a declared response length without trusting it for body bounds."""

    raw_length = headers.get("Content-Length")
    if raw_length is None:
        return None
    try:
        length = int(raw_length)
    except (TypeError, ValueError) as exc:
        raise ProviderResponseCaptureError(
            "Provider 响应长度头无效。", code="PROVIDER_RESPONSE_CONTENT_LENGTH_INVALID"
        ) from exc
    if length < 0:
        raise ProviderResponseCaptureError(
            "Provider 响应长度头无效。", code="PROVIDER_RESPONSE_CONTENT_LENGTH_INVALID"
        )
    if length > max_bytes:
        raise ProviderResponseCaptureError(
            "Provider 响应超过大小上限。", code="PROVIDER_RESPONSE_BODY_TOO_LARGE"
        )
    return length


def _decode_json_body(body: bytes) -> object:
    """Decode exact response bytes using the Domain's strict JSON contract."""

    try:
        return parse_provider_response_json(body)
    except ValueError as exc:
        raise ProviderResponseCaptureError(
            "Provider 响应不是严格 UTF-8 JSON。", code="PROVIDER_RESPONSE_JSON_INVALID"
        ) from exc


__all__ = [
    "ProviderResponseCaptureError",
    "ProviderResponseHttpProtocol",
    "capture_provider_response_body",
]
