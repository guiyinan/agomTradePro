"""Tushare-specific exact response capture adapter methods."""

from __future__ import annotations

from datetime import date

from apps.data_center.application.price_limit_response_capture import CapturedPriceLimitResponse
from apps.data_center.application.price_response_capture import CapturedPriceBarResponse
from apps.data_center.application.quote_response_capture import CapturedQuoteSnapshotResponse
from apps.data_center.application.quote_session_capture import CapturedQuoteSessionResponse
from apps.data_center.infrastructure._provider_adapter_base import BaseUnifiedProviderAdapter

from .provider_runtime_context import _deployment_region


class _TushareCaptureProviderAdapter(BaseUnifiedProviderAdapter):
    """Base the Tushare adapter uses for configured request and capture methods."""

    def _configured_request_mode(self) -> str | None:
        """Return this provider row's explicit Tushare transport mode."""

        raw_mode = (self._config.extra_config or {}).get("tushare_request_mode")
        return raw_mode.strip() if isinstance(raw_mode, str) and raw_mode.strip() else None

    def _capture_deployment_region(self) -> str:
        """Resolve the runtime region through the concrete adapter's compatibility seam."""

        return _deployment_region()

    def fetch_price_bar_with_capture(
        self,
        asset_code: str,
        target_trade_date: date,
    ) -> CapturedPriceBarResponse:
        """Fetch one exact daily bar while retaining bytes from that same call."""

        from apps.data_center.infrastructure.tushare_exact_price_capture import (
            fetch_exact_tushare_price_bar,
        )

        return fetch_exact_tushare_price_bar(
            self._config,
            asset_code=asset_code,
            target_trade_date=target_trade_date,
            deployment_region=self._capture_deployment_region(),
            request_mode=self._configured_request_mode(),
        )

    def fetch_price_limit_with_capture(
        self,
        asset_code: str,
        target_trade_date: date,
    ) -> CapturedPriceLimitResponse:
        """Capture exact provider-native daily bounds from one configured request."""

        from apps.data_center.infrastructure.tushare_exact_price_limit_capture import (
            fetch_exact_tushare_price_limit,
        )

        return fetch_exact_tushare_price_limit(
            self._config,
            asset_code=asset_code,
            target_trade_date=target_trade_date,
            deployment_region=self._capture_deployment_region(),
            request_mode=self._configured_request_mode(),
        )

    def fetch_quote_session_with_capture(
        self,
        asset_codes: list[str],
        target_trade_date: date,
    ) -> CapturedQuoteSessionResponse:
        """Fetch a full-market session with bytes from that same daily call."""

        from apps.data_center.infrastructure.tushare_session_quote_capture import (
            fetch_tushare_quote_session_with_capture,
        )

        return fetch_tushare_quote_session_with_capture(
            self._config,
            asset_codes=asset_codes,
            target_trade_date=target_trade_date,
            deployment_region=self._capture_deployment_region(),
            request_mode=self._configured_request_mode(),
        )

    def fetch_quote_snapshot_with_capture(
        self,
        asset_code: str,
        target_trade_date: date,
    ) -> CapturedQuoteSnapshotResponse:
        """Fetch one exact quote while preserving its response-byte carrier."""

        from apps.data_center.infrastructure.tushare_exact_quote_capture import (
            fetch_exact_tushare_quote_snapshot,
        )

        return fetch_exact_tushare_quote_snapshot(
            self._config,
            asset_code=asset_code,
            target_trade_date=target_trade_date,
            deployment_region=self._capture_deployment_region(),
            request_mode=self._configured_request_mode(),
        )
