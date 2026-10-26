"""Bounded helper functions for exact Tushare response capture and redaction."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from urllib.parse import parse_qsl, unquote, urlsplit

from apps.data_center.application.provider_response_payload import ProviderResponsePayloadReference
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
)
from apps.data_center.infrastructure.provider_response_capture import (
    ProviderResponseCaptureError,
    ProviderResponseHttpProtocol,
    capture_provider_response_body,
)
from core.exceptions import TushareError


@dataclass(frozen=True, slots=True)
class TushareResponseEvidence:
    """Exact response digest and completion time carried by one returned frame."""

    body_sha256: str
    response_completed_at: datetime
    raw_payload_scope: str = "batch_response_body"
    raw_payload_reference: ProviderResponsePayloadReference | None = None
    response_capture: ProviderResponseCapture | None = field(default=None, repr=False)
    sensitive_values: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        """Reject capture metadata that is detached from this frame's body."""

        if not re.fullmatch(r"[0-9a-f]{64}", self.body_sha256):
            raise ValueError("Tushare response body digest is invalid")
        if (
            self.response_completed_at.tzinfo is None
            or self.response_completed_at.utcoffset() is None
        ):
            raise ValueError("Tushare response completion time must be timezone-aware")
        capture = self.response_capture
        if capture is not None and (
            capture.body_sha256 != self.body_sha256
            or capture.response_completed_at != self.response_completed_at
        ):
            raise ValueError("Tushare response capture does not match frame evidence")

    def to_payload(self) -> dict[str, object]:
        """Return only cache-safe evidence; never serialize response bytes or secrets."""

        return {
            "body_sha256": self.body_sha256,
            "response_completed_at": self.response_completed_at.isoformat(),
            "time_semantics": "local_response_body_completion",
            "raw_payload_scope": self.raw_payload_scope,
            "raw_payload_reference": (
                self.raw_payload_reference.to_payload()
                if self.raw_payload_reference is not None
                else None
            ),
        }


class TushareProviderResponseHandler(Protocol):
    """Application-supplied handler for the legacy immediate-retention path."""

    def __call__(
        self,
        capture: ProviderResponseCapture,
        *,
        provider_name: str,
        dataset_key: str,
        api_name: str,
        request_params: Mapping[str, object],
        sensitive_values: tuple[str, ...],
    ) -> ProviderResponsePayloadReference:
        """Capture, retain, and return one exact reference."""
        ...


class _CaptureResponse(ProviderResponseHttpProtocol, Protocol):
    """HTTP response boundary with the cleanup operation used by capture."""

    def close(self) -> None:
        """Release the response stream."""
        ...


class _CaptureSession(Protocol):
    """Narrow direct requests-session surface needed to capture a response."""

    def post(self, url: str, **kwargs: object) -> _CaptureResponse:
        """Send a streaming POST."""
        ...

    def get(self, url: str, **kwargs: object) -> _CaptureResponse:
        """Send a streaming GET."""
        ...


class TushareRelayAuthorizationError(PermissionError):
    """Raised when the configured relay rejects its Tushare credential."""


def capture_direct_provider_response(
    session: _CaptureSession,
    target_url: str,
    *,
    method: str,
    params: Mapping[str, object] | None,
    json_body: Mapping[str, object] | None,
    timeout_seconds: int,
) -> ProviderResponseCapture:
    """Capture a direct HTTP response without reserializing parsed rows."""

    normalized_method = method.upper()
    request_headers = {"Accept-Encoding": "identity"}
    request_kwargs: dict[str, object] = {
        "params": params,
        "headers": request_headers,
        "timeout": timeout_seconds,
        "allow_redirects": False,
        "stream": True,
    }
    if normalized_method == "POST":
        response = session.post(target_url, json=json_body, **request_kwargs)
    elif normalized_method == "GET":
        response = session.get(target_url, **request_kwargs)
    else:
        raise TushareError(
            "Tushare response capture method is unsupported",
            code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_INVALID",
        )
    try:
        if response.status_code in {401, 403}:
            raise TushareRelayAuthorizationError(
                f"Tushare relay authorization failed with HTTP {response.status_code}"
            )
        if 300 <= response.status_code < 400:
            raise TushareError(
                "Tushare response redirect was rejected",
                code="TUSHARE_REDIRECT_BLOCKED",
            )
        if not 200 <= response.status_code < 300:
            raise TushareError(
                "Tushare relay returned an HTTP error",
                code=f"TUSHARE_HTTP_{response.status_code}",
            )
        try:
            return capture_provider_response_body(
                response,
                transport=ProviderResponseTransport.DIRECT,
                max_bytes=4 * 1024 * 1024,
            )
        except ProviderResponseCaptureError as exc:
            raise TushareError(
                "Tushare exact response bytes could not be captured",
                code=exc.code,
            ) from exc
    finally:
        response.close()


def capture_sensitive_values(
    *,
    token: str,
    target_url: str,
    headers: Mapping[str, str],
    request_params: Mapping[str, object],
) -> tuple[str, ...]:
    """Collect credential literals that must be scrubbed from retained JSON."""

    values = {token} if token else set()

    def visit(value: object) -> None:
        """Collect secret literals from nested request dimensions."""

        if isinstance(value, Mapping):
            for key, item in value.items():
                if isinstance(key, str) and _is_credential_name(key) and isinstance(item, str):
                    if item:
                        values.add(item)
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(request_params)
    for name, value in headers.items():
        if _is_credential_name(name) and value:
            values.add(value)
            if " " in value:
                values.add(value.split(" ", 1)[1].strip())
            for part in value.split(";"):
                candidate = part.strip().split("=", 1)[-1].strip()
                if candidate:
                    values.add(candidate)
    try:
        parsed = urlsplit(target_url)
    except ValueError as exc:
        raise TushareError(
            "Provider capture target could not be safely inspected",
            code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_INVALID",
        ) from exc
    for credential in (parsed.username, parsed.password):
        if credential:
            values.add(credential)
            values.add(unquote(credential))
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_credential_name(key) and value:
            values.add(value)
    return tuple(sorted(values, key=lambda item: (-len(item), item)))


def retain_provider_response(
    handler: TushareProviderResponseHandler,
    capture: ProviderResponseCapture,
    *,
    token: str,
    target_url: str,
    headers: Mapping[str, str],
    dataset_key: str,
    api_name: str,
    request_params: Mapping[str, object],
) -> ProviderResponsePayloadReference:
    """Invoke the legacy immediate-retention handler with complete redaction inputs."""

    reference = handler(
        capture,
        provider_name="tushare",
        dataset_key=dataset_key or f"tushare.{api_name}",
        api_name=api_name,
        request_params=request_params,
        sensitive_values=capture_sensitive_values(
            token=token,
            target_url=target_url,
            headers=headers,
            request_params=request_params,
        ),
    )
    if not isinstance(reference, ProviderResponsePayloadReference):
        raise TushareError(
            "Provider response handler returned an invalid reference",
            code="TUSHARE_PROVIDER_RESPONSE_REFERENCE_INVALID",
        )
    return reference


def build_tushare_response_evidence(
    capture: ProviderResponseCapture,
    *,
    handler: TushareProviderResponseHandler | None,
    token: str,
    target_url: str,
    headers: Mapping[str, str],
    dataset_key: str,
    api_name: str,
    request_params: Mapping[str, object],
) -> TushareResponseEvidence:
    """Attach one response and its redaction inputs to the returned frame."""

    sensitive_values = capture_sensitive_values(
        token=token,
        target_url=target_url,
        headers=headers,
        request_params=request_params,
    )
    reference = (
        retain_provider_response(
            handler,
            capture,
            token=token,
            target_url=target_url,
            headers=headers,
            dataset_key=dataset_key,
            api_name=api_name,
            request_params=request_params,
        )
        if handler is not None
        else None
    )
    return TushareResponseEvidence(
        body_sha256=capture.body_sha256,
        response_completed_at=capture.response_completed_at,
        raw_payload_reference=reference,
        response_capture=capture,
        sensitive_values=sensitive_values,
    )


def _is_credential_name(value: str) -> bool:
    """Recognize narrowly named credential-bearing URL/header/JSON fields."""

    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    return any(
        marker in normalized
        for marker in (
            "apikey",
            "authorization",
            "cookie",
            "credential",
            "password",
            "secret",
            "token",
        )
    )


__all__ = [
    "TushareProviderResponseHandler",
    "TushareRelayAuthorizationError",
    "TushareResponseEvidence",
    "build_tushare_response_evidence",
    "capture_direct_provider_response",
    "capture_sensitive_values",
    "retain_provider_response",
]
