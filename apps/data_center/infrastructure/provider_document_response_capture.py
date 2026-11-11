"""Read and bind exact identity-encoded provider document response bytes."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from urllib3.exceptions import HTTPError

from apps.data_center.application.egress_service import EgressTransportResult
from apps.data_center.domain.egress_routing import EgressRequestContext, target_hostname
from apps.data_center.domain.provider_document_response import (
    ProviderDocumentResponseCapture,
    normalize_document_content_type,
    normalize_document_media_type_allowlist,
)
from apps.data_center.domain.provider_response import ProviderResponseTransport
from core.exceptions import DataFetchError


class ProviderDocumentResponseCaptureError(DataFetchError):
    """Raised when an HTTP body cannot be retained as exact document bytes."""

    default_message = "Provider 文档响应字节无法安全捕获。"
    default_code = "PROVIDER_DOCUMENT_CAPTURE_FAILED"


class _DocumentRequestExecutorProtocol(Protocol):
    """Narrow callback surface for the existing pinned egress request core."""

    _max_response_bytes: int

    def _request_once(
        self,
        context: EgressRequestContext,
        *,
        egress_id: int | None,
        attempt: int,
        method: str,
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        expect_json: bool,
        max_response_bytes: int,
        document_capture_request_id: UUID | None,
        document_capture_allowed_media_types: frozenset[str] | None,
    ) -> tuple[EgressTransportResult, object | None]:
        """Perform one request through the existing public-target guard."""
        ...


def execute_provider_document_http_request(
    executor: _DocumentRequestExecutorProtocol,
    context: EgressRequestContext,
    *,
    egress_id: int | None,
    request_id: UUID,
    attempt: int,
    max_bytes: int,
    allowed_media_types: frozenset[str],
) -> tuple[EgressTransportResult, ProviderDocumentResponseCapture | None]:
    """Validate one raw-document request before using the pinned HTTP core."""

    try:
        normalized_types = prepare_provider_document_request(
            request_id=request_id,
            attempt=attempt,
            egress_id=egress_id,
            max_bytes=max_bytes,
            configured_max_bytes=executor._max_response_bytes,
            allowed_media_types=allowed_media_types,
        )
    except ProviderDocumentResponseCaptureError as exc:
        return (
            EgressTransportResult(
                outcome="blocked",
                error_code=exc.code,
                message="原始文档请求未通过安全校验。",
                retryable=False,
            ),
            None,
        )
    result, payload = executor._request_once(
        context,
        egress_id=egress_id,
        attempt=attempt,
        method="GET",
        params=None,
        json_body=None,
        headers={"Accept-Encoding": "identity"},
        expect_json=False,
        max_response_bytes=max_bytes,
        document_capture_request_id=request_id,
        document_capture_allowed_media_types=normalized_types,
    )
    if isinstance(payload, ProviderDocumentResponseCapture):
        return result, payload
    return result, None


class _ResponseBodyStream(Protocol):
    """The requests raw stream surface needed to avoid transparent decoding."""

    def stream(self, amt: int, decode_content: bool = False) -> Iterator[bytes]:
        """Yield raw HTTP entity bytes in bounded chunks."""
        ...


class ProviderDocumentResponseHttpProtocol(Protocol):
    """Minimal successful response surface used by the exact byte reader."""

    status_code: int
    headers: Mapping[str, str]
    raw: _ResponseBodyStream


def capture_provider_document_response(
    response: ProviderDocumentResponseHttpProtocol,
    *,
    request_id: UUID,
    attempt: int,
    egress_id: int | None,
    target_url: str,
    transport: ProviderResponseTransport,
    max_bytes: int,
    allowed_media_types: frozenset[str],
) -> ProviderDocumentResponseCapture:
    """Read one bounded identity-encoded response without decoding its bytes."""

    if not isinstance(transport, ProviderResponseTransport):
        raise ProviderDocumentResponseCaptureError(
            "文档响应传输标记无效。", code="PROVIDER_DOCUMENT_CAPTURE_INVALID"
        )
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ProviderDocumentResponseCaptureError(
            "文档响应大小上限无效。", code="PROVIDER_DOCUMENT_CAPTURE_INVALID"
        )
    try:
        accepted_media_types = normalize_document_media_type_allowlist(allowed_media_types)
    except ValueError as exc:
        raise ProviderDocumentResponseCaptureError(
            "文档响应 MIME allowlist 无效。", code="PROVIDER_DOCUMENT_CAPTURE_INVALID"
        ) from exc

    if (
        isinstance(response.status_code, bool)
        or not isinstance(response.status_code, int)
        or not 200 <= response.status_code < 300
    ):
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应状态不是成功。", code="PROVIDER_DOCUMENT_HTTP_FAILED"
        )

    content_encoding = _header(response.headers, "content-encoding")
    if content_encoding is not None and content_encoding.strip().casefold() not in {
        "",
        "identity",
    }:
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应使用了非 identity 编码。",
            code="PROVIDER_DOCUMENT_ENCODING_UNSUPPORTED",
        )
    raw_content_type = _header(response.headers, "content-type")
    if raw_content_type is None:
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应 Content-Type 缺失。",
            code="PROVIDER_DOCUMENT_CONTENT_TYPE_INVALID",
        )
    try:
        media_type = normalize_document_content_type(raw_content_type)
    except ValueError as exc:
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应 Content-Type 无效。",
            code="PROVIDER_DOCUMENT_CONTENT_TYPE_INVALID",
        ) from exc
    if media_type not in accepted_media_types:
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应 MIME 不在明确允许范围内。",
            code="PROVIDER_DOCUMENT_MEDIA_TYPE_REJECTED",
        )
    expected_size = _content_length(response.headers, max_bytes)
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.raw.stream(16 * 1024, decode_content=False):
            if type(chunk) is not bytes:
                raise ValueError("response_stream_chunk_not_bytes")
            if not chunk:
                continue
            if len(chunk) > max_bytes - total:
                raise ProviderDocumentResponseCaptureError(
                    "Provider 文档响应超过大小上限。",
                    code="PROVIDER_DOCUMENT_BODY_TOO_LARGE",
                )
            total += len(chunk)
            chunks.append(chunk)
    except ProviderDocumentResponseCaptureError:
        raise
    except (AttributeError, HTTPError, OSError, TypeError, ValueError) as exc:
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应读取未完整完成。",
            code="PROVIDER_DOCUMENT_BODY_READ_FAILED",
        ) from exc

    if expected_size is not None and total != expected_size:
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应声明长度与已读取字节不符。",
            code="PROVIDER_DOCUMENT_BODY_TRUNCATED",
        )
    body = b"".join(chunks)
    if not body:
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应正文为空。", code="PROVIDER_DOCUMENT_EMPTY_BODY"
        )
    completed_at = datetime.now(UTC)
    try:
        normalized_host = target_hostname(target_url)
        return ProviderDocumentResponseCapture(
            request_id=request_id,
            attempt=attempt,
            egress_id=egress_id,
            target_url_sha256=hashlib.sha256(target_url.encode("utf-8")).hexdigest(),
            target_host=normalized_host,
            body=body,
            body_sha256=hashlib.sha256(body).hexdigest(),
            body_size_bytes=len(body),
            response_completed_at=completed_at,
            status_code=response.status_code,
            content_type=raw_content_type,
            transport=transport,
        )
    except (UnicodeEncodeError, ValueError) as exc:
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应捕获元数据无效。",
            code="PROVIDER_DOCUMENT_CAPTURE_INVALID",
        ) from exc


def prepare_provider_document_request(
    *,
    request_id: UUID,
    attempt: int,
    egress_id: int | None,
    max_bytes: int,
    configured_max_bytes: int,
    allowed_media_types: frozenset[str],
) -> frozenset[str]:
    """Validate the per-request byte cap and exact concrete MIME allowlist."""

    if (
        not isinstance(request_id, UUID)
        or isinstance(attempt, bool)
        or not isinstance(attempt, int)
        or attempt < 1
    ):
        raise ProviderDocumentResponseCaptureError(
            "文档请求标识无效。", code="EGRESS_DOCUMENT_CAPTURE_INVALID"
        )
    if egress_id is not None and (
        isinstance(egress_id, bool) or not isinstance(egress_id, int) or egress_id < 1
    ):
        raise ProviderDocumentResponseCaptureError(
            "文档出口标识无效。", code="EGRESS_DOCUMENT_CAPTURE_INVALID"
        )
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or not 1 <= max_bytes <= configured_max_bytes
    ):
        raise ProviderDocumentResponseCaptureError(
            "文档响应大小上限无效。", code="EGRESS_DOCUMENT_BODY_LIMIT_INVALID"
        )
    try:
        accepted_types = normalize_document_media_type_allowlist(allowed_media_types)
    except ValueError as exc:
        raise ProviderDocumentResponseCaptureError(
            "文档响应 MIME allowlist 无效。", code="EGRESS_DOCUMENT_MEDIA_TYPES_INVALID"
        ) from exc
    return accepted_types


def capture_provider_document_response_result(
    response: ProviderDocumentResponseHttpProtocol,
    *,
    request_id: UUID,
    attempt: int,
    egress_id: int | None,
    target_url: str,
    max_bytes: int,
    allowed_media_types: frozenset[str],
    started: float,
) -> tuple[EgressTransportResult, ProviderDocumentResponseCapture | None]:
    """Project exact byte capture success or a sanitized retryable outcome."""

    try:
        capture = capture_provider_document_response(
            response,
            request_id=request_id,
            attempt=attempt,
            egress_id=egress_id,
            target_url=target_url,
            transport=ProviderResponseTransport.EGRESS,
            max_bytes=max_bytes,
            allowed_media_types=allowed_media_types,
        )
    except ProviderDocumentResponseCaptureError as exc:
        retryable = exc.code in {
            "PROVIDER_DOCUMENT_BODY_READ_FAILED",
            "PROVIDER_DOCUMENT_BODY_TRUNCATED",
        }
        return (
            EgressTransportResult(
                outcome="failed",
                error_code=exc.code,
                message="Provider 文档原始响应捕获失败。",
                status_code=response.status_code,
                latency_ms=round((time.monotonic() - started) * 1000, 3),
                retryable=retryable,
            ),
            None,
        )
    return (
        EgressTransportResult(
            outcome="success",
            status_code=response.status_code,
            latency_ms=round((time.monotonic() - started) * 1000, 3),
            retryable=False,
        ),
        capture,
    )


def _header(headers: Mapping[str, str], key: str) -> str | None:
    """Return one case-insensitive response header, rejecting ambiguity."""

    matches: list[str] = []
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ProviderDocumentResponseCaptureError(
                "Provider 文档响应头无效。", code="PROVIDER_DOCUMENT_HEADER_INVALID"
            )
        if name.casefold() == key:
            matches.append(value)
    if len(matches) > 1:
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应头重复。", code="PROVIDER_DOCUMENT_HEADER_INVALID"
        )
    return matches[0] if matches else None


def _content_length(headers: Mapping[str, str], max_bytes: int) -> int | None:
    """Validate a declared response length without trusting it for body bounds."""

    raw_length = _header(headers, "content-length")
    if raw_length is None:
        return None
    if not raw_length or not raw_length.isascii() or not raw_length.isdecimal():
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应长度头无效。",
            code="PROVIDER_DOCUMENT_CONTENT_LENGTH_INVALID",
        )
    significant = raw_length.lstrip("0") or "0"
    maximum = str(max_bytes)
    if len(significant) > len(maximum) or (
        len(significant) == len(maximum) and significant > maximum
    ):
        raise ProviderDocumentResponseCaptureError(
            "Provider 文档响应超过大小上限。",
            code="PROVIDER_DOCUMENT_BODY_TOO_LARGE",
        )
    return int(significant)


__all__ = [
    "ProviderDocumentResponseCaptureError",
    "ProviderDocumentResponseHttpProtocol",
    "capture_provider_document_response",
    "capture_provider_document_response_result",
    "execute_provider_document_http_request",
    "prepare_provider_document_request",
]
