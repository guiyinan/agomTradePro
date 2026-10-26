"""Typed request and capture result for one exact Tushare quote response."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable

from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.domain.entities import QuoteSnapshot
from apps.data_center.domain.provider_response import ProviderResponseCapture

_ASSET_CODE = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)\Z")


@dataclass(frozen=True, slots=True)
class ExactQuoteRequestScope:
    """Bind one exact provider request before its response body is fetched."""

    provider_id: int
    provider_name: str
    dataset_key: str
    api_name: str
    asset_code: str
    trade_date: date

    def __post_init__(self) -> None:
        """Reject scopes that cannot identify one configured A-share daily call."""

        if isinstance(self.provider_id, bool) or not isinstance(self.provider_id, int):
            raise ValueError("provider_id must be an integer")
        if self.provider_id < 1:
            raise ValueError("provider_id must be positive")
        if (
            not isinstance(self.provider_name, str)
            or not self.provider_name.strip()
            or len(self.provider_name) > 100
        ):
            raise ValueError("provider_name must be bounded non-empty text")
        if self.dataset_key != "equity.quote.snapshot" or self.api_name != "daily":
            raise ValueError("quote request scope is unsupported")
        if not isinstance(self.asset_code, str) or _ASSET_CODE.fullmatch(self.asset_code) is None:
            raise ValueError("asset_code must be one canonical A-share code")
        if type(self.trade_date) is not date:
            raise ValueError("trade_date must be a date")

    def request_params(self) -> dict[str, object]:
        """Return safe exact request metadata for RawPayload redaction and hashing."""

        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "api_name": self.api_name,
            "fields": "",
            "params": {
                "ts_code": self.asset_code,
                "trade_date": self.trade_date.strftime("%Y%m%d"),
            },
        }

    def to_payload(self) -> dict[str, object]:
        """Return safe identity metadata; no response body or credentials are included."""

        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "api_name": self.api_name,
            "asset_code": self.asset_code,
            "trade_date": self.trade_date.isoformat(),
            "request_params": self.request_params(),
        }


@dataclass(frozen=True, slots=True)
class CapturedQuoteSnapshotResponse:
    """Carry one parsed quote with its exact same-call response bytes."""

    request_scope: ExactQuoteRequestScope
    quote: QuoteSnapshot
    capture: ProviderResponseCapture = field(repr=False)
    sensitive_values: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        """Require typed values before this response crosses the provider boundary."""

        if not isinstance(self.request_scope, ExactQuoteRequestScope):
            raise TypeError("request_scope must be ExactQuoteRequestScope")
        if not isinstance(self.quote, QuoteSnapshot):
            raise TypeError("quote must be QuoteSnapshot")
        if not isinstance(self.capture, ProviderResponseCapture):
            raise TypeError("capture must be ProviderResponseCapture")
        if not self.capture.payload_matches_body():
            raise ValueError("captured response bytes do not match parsed payload")
        if any(not isinstance(value, str) or not value for value in self.sensitive_values):
            raise ValueError("sensitive_values must contain non-empty text")


@runtime_checkable
class ExactQuoteResponseProviderProtocol(Protocol):
    """Optional provider capability for one exact daily quote with raw bytes."""

    def fetch_quote_snapshot_with_capture(
        self, asset_code: str, target_trade_date: date
    ) -> CapturedQuoteSnapshotResponse:
        """Fetch one asset/session and return its exact response capture."""
        ...


class ProviderResponsePayloadRetainerProtocol(Protocol):
    """Application port for persisting one capture inside the final sync UOW."""

    def execute(
        self,
        capture: ProviderResponseCapture,
        *,
        provider_name: str,
        dataset_key: str,
        api_name: str,
        request_params: dict[str, object],
        sensitive_values: tuple[str, ...],
        run_id: str,
    ) -> ProviderResponsePayloadReference:
        """Persist a redacted payload under the already-issued run identity."""
        ...


__all__ = [
    "CapturedQuoteSnapshotResponse",
    "ExactQuoteRequestScope",
    "ExactQuoteResponseProviderProtocol",
    "ProviderResponsePayloadRetainerProtocol",
]
