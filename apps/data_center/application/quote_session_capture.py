"""Typed request, transport, and lineage values for full-session quote capture."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable

from apps.data_center.application.full_market_task_support import asset_code_scope_sha256
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.application.sync_identity import SyncExecutionIdentity
from apps.data_center.domain.entities import QuoteSnapshot
from apps.data_center.domain.provider_response import ProviderResponseCapture
from core.exceptions import DataFetchError

_CAPTURE_EVIDENCE_SCHEMA = "quote-session-capture-v1"
_ASSET_CODE = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)\Z")


@dataclass(frozen=True, slots=True)
class QuoteSessionRequestScope:
    """Bind one daily provider response to the full frozen quote universe."""

    provider_id: int
    provider_name: str
    dataset_key: str
    api_name: str
    asset_codes: tuple[str, ...]
    target_trade_date: date

    def __post_init__(self) -> None:
        """Reject request scopes that could name an incomplete or different call."""

        if isinstance(self.provider_id, bool) or not isinstance(self.provider_id, int):
            raise ValueError("provider_id must be an integer")
        if self.provider_id <= 0:
            raise ValueError("provider_id must be positive")
        if (
            not isinstance(self.provider_name, str)
            or not self.provider_name.strip()
            or len(self.provider_name) > 100
        ):
            raise ValueError("provider_name must be bounded non-empty text")
        if self.dataset_key != "equity.quote.snapshot":
            raise ValueError("quote session dataset_key is unsupported")
        if self.api_name != "daily":
            raise ValueError("quote session api_name is unsupported")
        if type(self.target_trade_date) is not date:
            raise ValueError("target_trade_date must be a date")
        if (
            not isinstance(self.asset_codes, tuple)
            or not self.asset_codes
            or any(
                type(code) is not str or _ASSET_CODE.fullmatch(code) is None
                for code in self.asset_codes
            )
            or self.asset_codes != tuple(sorted(set(self.asset_codes)))
        ):
            raise ValueError("asset_codes must be a canonical frozen quote universe")

    @property
    def universe_sha256(self) -> str:
        """Return the canonical digest of the complete requested universe."""

        return asset_code_scope_sha256(self.asset_codes)

    def request_params(self) -> dict[str, object]:
        """Return the actual daily date and full filtered scope for RawPayload."""

        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "api_name": self.api_name,
            "params": {"trade_date": self.target_trade_date.strftime("%Y%m%d")},
            "quote_session_scope": {
                "asset_codes": list(self.asset_codes),
                "asset_count": len(self.asset_codes),
                "universe_sha256": self.universe_sha256,
            },
        }

    def to_payload(self) -> dict[str, object]:
        """Return safe scope metadata without copying the full universe into facts."""

        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "api_name": self.api_name,
            "target_trade_date": self.target_trade_date.isoformat(),
            "asset_count": len(self.asset_codes),
            "universe_sha256": self.universe_sha256,
        }


@dataclass(frozen=True, slots=True)
class CapturedQuoteSessionResponse:
    """Carry normalized rows and exact bytes from one full-session provider call."""

    request_scope: QuoteSessionRequestScope
    quotes: tuple[QuoteSnapshot, ...]
    capture: ProviderResponseCapture = field(repr=False)
    sensitive_values: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        """Require typed rows and a byte-bound successful response before use."""

        if not isinstance(self.request_scope, QuoteSessionRequestScope):
            raise TypeError("request_scope must be QuoteSessionRequestScope")
        if not isinstance(self.quotes, tuple) or any(
            not isinstance(quote, QuoteSnapshot) for quote in self.quotes
        ):
            raise TypeError("quotes must be a tuple of QuoteSnapshot")
        if not isinstance(self.capture, ProviderResponseCapture):
            raise TypeError("capture must be ProviderResponseCapture")
        if not self.capture.payload_matches_body():
            raise ValueError("captured response bytes do not match parsed payload")
        if not isinstance(self.sensitive_values, tuple) or any(
            not isinstance(value, str) or not value for value in self.sensitive_values
        ):
            raise ValueError("sensitive_values must contain non-empty text")


@dataclass(frozen=True, slots=True)
class QuoteSessionCaptureOrigin:
    """Identify the server-issued sync execution that retained the full response."""

    identity: SyncExecutionIdentity
    request_scope: QuoteSessionRequestScope

    def __post_init__(self) -> None:
        """Require the persisted identity to name the captured provider dataset."""

        if not isinstance(self.identity, SyncExecutionIdentity):
            raise TypeError("identity must be SyncExecutionIdentity")
        if not isinstance(self.request_scope, QuoteSessionRequestScope):
            raise TypeError("request_scope must be QuoteSessionRequestScope")
        if (
            self.identity.dataset_key != self.request_scope.dataset_key
            or self.identity.provider_name != self.request_scope.provider_name
        ):
            raise ValueError("capture origin identity does not match its request scope")

    def to_payload(self) -> dict[str, object]:
        """Return all persisted identity fields used by the capture lineage."""

        return {
            "run_id": self.identity.run_id,
            "ingested_run_id": self.identity.ingested_run_id,
            "batch_id": self.identity.batch_id,
            "dataset_key": self.identity.dataset_key,
            "provider_name": self.identity.provider_name,
            "identity_hash": self.identity.identity_hash,
        }


@dataclass(frozen=True, slots=True)
class RetainedQuoteSessionCapture:
    """Bind one server-issued capture origin to its immutable payload reference."""

    capture_origin: QuoteSessionCaptureOrigin
    payload_reference: ProviderResponsePayloadReference


class QuoteSessionCaptureBinder(Protocol):
    """Persist one validated session response and return its exact lineage binding."""

    def bind(self, response: CapturedQuoteSessionResponse) -> RetainedQuoteSessionCapture:
        """Issue the capture identity and retain the response exactly once."""


@runtime_checkable
class SessionQuoteResponseProviderProtocol(Protocol):
    """Optional provider capability returning rows and bytes from one session call."""

    def fetch_quote_session_with_capture(
        self, asset_codes: list[str], target_trade_date: date
    ) -> CapturedQuoteSessionResponse:
        """Fetch one exact full-session response and preserve its transport bytes."""


def validate_quote_session_capture_binding(
    capture_origin: QuoteSessionCaptureOrigin,
    payload_reference: ProviderResponsePayloadReference,
    *,
    request_scope: QuoteSessionRequestScope,
    response: CapturedQuoteSessionResponse | None = None,
) -> None:
    """Fail closed unless the persisted reference matches its full-session origin."""

    if not isinstance(capture_origin, QuoteSessionCaptureOrigin):
        raise DataFetchError(
            "Quote session capture origin is invalid",
            code="CURRENT_QUOTE_SESSION_CAPTURE_ORIGIN_INVALID",
        )
    if not isinstance(payload_reference, ProviderResponsePayloadReference):
        raise DataFetchError(
            "Quote session payload reference is invalid",
            code="CURRENT_QUOTE_SESSION_CAPTURE_REFERENCE_INVALID",
        )
    if capture_origin.request_scope != request_scope:
        raise DataFetchError(
            "Quote session capture origin scope changed",
            code="CURRENT_QUOTE_SESSION_CAPTURE_SCOPE_MISMATCH",
        )
    identity = capture_origin.identity
    if (
        identity.dataset_key != request_scope.dataset_key
        or identity.provider_name != request_scope.provider_name
        or payload_reference.dataset_key != request_scope.dataset_key
        or payload_reference.provider_name != request_scope.provider_name
        or payload_reference.run_id != identity.run_id
    ):
        raise DataFetchError(
            "Quote session payload reference does not match its capture identity",
            code="CURRENT_QUOTE_SESSION_CAPTURE_REFERENCE_MISMATCH",
        )
    if response is not None:
        if (
            response.request_scope != request_scope
            or payload_reference.body_sha256 != response.capture.body_sha256
            or payload_reference.body_size_bytes != response.capture.body_size_bytes
            or payload_reference.response_completed_at != response.capture.response_completed_at
            or payload_reference.transport != response.capture.transport
        ):
            raise DataFetchError(
                "Quote session payload reference does not match its response bytes",
                code="CURRENT_QUOTE_SESSION_CAPTURE_REFERENCE_MISMATCH",
            )


def quote_session_capture_evidence(
    capture_origin: QuoteSessionCaptureOrigin,
    payload_reference: ProviderResponsePayloadReference,
    *,
    available_codes: tuple[str, ...],
    eligible_codes: tuple[str, ...],
    excluded_codes: tuple[str, ...],
    quote_rows_sha256: str,
) -> dict[str, object]:
    """Build the same compact, hash-safe capture binding for facts and RawAudits."""

    request_scope = capture_origin.request_scope
    validate_quote_session_capture_binding(
        capture_origin,
        payload_reference,
        request_scope=request_scope,
    )
    if not isinstance(quote_rows_sha256, str) or len(quote_rows_sha256) != 64:
        raise DataFetchError(
            "Quote session row digest is invalid",
            code="CURRENT_QUOTE_SESSION_CAPTURE_EVIDENCE_INVALID",
        )
    for value in (quote_rows_sha256,):
        if any(character not in "0123456789abcdef" for character in value):
            raise DataFetchError(
                "Quote session row digest is invalid",
                code="CURRENT_QUOTE_SESSION_CAPTURE_EVIDENCE_INVALID",
            )
    for codes in (available_codes, eligible_codes, excluded_codes):
        if (
            not isinstance(codes, tuple)
            or any(type(code) is not str or _ASSET_CODE.fullmatch(code) is None for code in codes)
            or codes != tuple(sorted(set(codes)))
        ):
            raise DataFetchError(
                "Quote session capture code scope is invalid",
                code="CURRENT_QUOTE_SESSION_CAPTURE_EVIDENCE_INVALID",
            )
    available_set = set(available_codes)
    excluded_set = set(excluded_codes)
    if (
        eligible_codes != available_codes
        or available_set.intersection(excluded_set)
        or available_set.union(excluded_set) != set(request_scope.asset_codes)
    ):
        raise DataFetchError(
            "Quote session capture code partitions do not cover the frozen universe",
            code="CURRENT_QUOTE_SESSION_CAPTURE_EVIDENCE_INVALID",
        )
    return {
        "schema": _CAPTURE_EVIDENCE_SCHEMA,
        "origin": capture_origin.to_payload(),
        "request_scope": request_scope.to_payload(),
        "universe_sha256": request_scope.universe_sha256,
        "available_codes_sha256": asset_code_scope_sha256(available_codes),
        "eligible_codes_sha256": asset_code_scope_sha256(eligible_codes),
        "excluded_codes_sha256": asset_code_scope_sha256(excluded_codes),
        "quote_rows_sha256": quote_rows_sha256,
        "response_completed_at": payload_reference.response_completed_at.isoformat(),
        "payload_reference": payload_reference.to_payload(),
    }


__all__ = [
    "CapturedQuoteSessionResponse",
    "QuoteSessionCaptureBinder",
    "QuoteSessionCaptureOrigin",
    "QuoteSessionRequestScope",
    "RetainedQuoteSessionCapture",
    "SessionQuoteResponseProviderProtocol",
    "quote_session_capture_evidence",
    "validate_quote_session_capture_binding",
]
