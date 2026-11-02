"""Application entry for one exact, read-only Sina quote response capture."""

from __future__ import annotations

from typing import Protocol

from apps.data_center.domain.sina_quote_capture import (
    SinaQuoteCapture,
    SinaQuoteCaptureValidationError,
    SinaQuoteObservation,
    build_sina_quote_request_url,
)


class SinaQuoteTransportProtocol(Protocol):
    """Capture and normalize one Sina response at the infrastructure boundary."""

    def fetch_quote_capture(self, asset_code: str) -> SinaQuoteCapture:
        """Return one bounded raw response and its validated Sina quote row."""
        ...


class CaptureSinaQuoteUseCase:
    """Request one exact Sina source capture through the Data Center provider port."""

    def __init__(self, *, transport: SinaQuoteTransportProtocol) -> None:
        """Inject a Data Center transport; construction performs no network access."""

        self._transport = transport

    def execute(self, asset_code: str) -> SinaQuoteCapture:
        """Return one same-response capture while keeping source and local clocks apart."""

        build_sina_quote_request_url(asset_code)
        capture = self._transport.fetch_quote_capture(asset_code)
        if type(capture) is not SinaQuoteCapture or capture.asset_code != asset_code:
            raise SinaQuoteCaptureValidationError("Sina provider returned a mismatched capture")
        capture.__post_init__()
        return capture


__all__ = (
    "CaptureSinaQuoteUseCase",
    "SinaQuoteCapture",
    "SinaQuoteObservation",
    "SinaQuoteTransportProtocol",
)
