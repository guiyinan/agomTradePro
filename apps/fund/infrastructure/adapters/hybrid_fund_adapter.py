"""Validated multi-source fund adapter with backend-safe shared cache keys."""

from __future__ import annotations

import importlib
import logging
import re
from typing import Protocol, cast

from shared.infrastructure.resilience import (
    DataSourceUnavailable,
    HealthStatus,
    _health_manager,
    cached,
    retry_on_error,
)

logger = logging.getLogger(__name__)

_FUND_CODE_PATTERN = re.compile(r"\d{6}(?:\.(?:OF|SH|SZ))?\Z")


class FundDataFrame(Protocol):
    """Narrow pandas DataFrame behavior required at this provider boundary."""

    @property
    def empty(self) -> bool:
        """Return whether the frame contains no rows."""


class _PandasModule(Protocol):
    def DataFrame(self, data: object = None) -> FundDataFrame:
        """Construct an empty or populated frame."""


class _AkShareFundAdapter(Protocol):
    def fetch_fund_list_em(self) -> FundDataFrame: ...

    def fetch_fund_info_em(self, fund_code: str) -> FundDataFrame: ...

    def fetch_fund_nav_em(self, fund_code: str) -> FundDataFrame: ...


class _TushareFundAdapter(Protocol):
    def fetch_fund_list(self, market: str = "E") -> FundDataFrame: ...


pd = cast(_PandasModule, importlib.import_module("pandas"))


def _fund_list_cache_key(_adapter: object) -> str:
    """Return a process-independent, Memcached-safe fund list cache key."""

    return "fund:list:em:v1"


def _normalize_fund_code(fund_code: object) -> str:
    """Validate a dynamic fund code before provider or cache access."""

    if not isinstance(fund_code, str):
        raise ValueError("fund_code must be a string")
    normalized = fund_code.strip().upper()
    if not _FUND_CODE_PATTERN.fullmatch(normalized):
        raise ValueError("fund_code must be a six-digit mainland fund code")
    return normalized


def _fund_info_cache_key(fund_code: str) -> str:
    """Return the stable exact-fund information cache key."""

    return f"fund:info:em:v1:{_normalize_fund_code(fund_code)}"


def _fund_nav_cache_key(fund_code: str) -> str:
    """Return the stable exact-fund NAV cache key."""

    return f"fund:nav:em:v1:{_normalize_fund_code(fund_code)}"


class HybridFundAdapter:
    """Fetch fund data through healthy providers with deterministic degradation."""

    def __init__(
        self,
        tushare_token: str | None = None,
        tushare_http_url: str | None = None,
    ) -> None:
        self.tushare_token = tushare_token
        self.tushare_http_url = tushare_http_url
        self._akshare_adapter: _AkShareFundAdapter | None = None
        self._tushare_adapter: _TushareFundAdapter | None = None

    @property
    def akshare(self) -> _AkShareFundAdapter:
        """Lazily construct the AKShare provider adapter."""

        if self._akshare_adapter is None:
            from .akshare_fund_adapter import AkShareFundAdapter

            self._akshare_adapter = AkShareFundAdapter()
        return self._akshare_adapter

    @property
    def tushare(self) -> _TushareFundAdapter:
        """Lazily construct the configured Tushare provider adapter."""

        if self._tushare_adapter is None:
            if not self.tushare_token:
                raise ValueError("Tushare token is not configured")
            from .tushare_fund_adapter import TushareFundAdapter

            self._tushare_adapter = TushareFundAdapter(
                token=self.tushare_token,
                http_url=self.tushare_http_url,
            )
        return self._tushare_adapter

    @retry_on_error(
        max_retries=3,
        initial_delay=1.0,
        backoff_factor=2.0,
        exceptions=(ConnectionError, TimeoutError, DataSourceUnavailable),
    )
    @cached(ttl=7200, key_func=_fund_list_cache_key)
    def fetch_fund_list_em(self) -> FundDataFrame:
        """Return the complete fund list from the first healthy non-empty source."""

        try:
            if _health_manager.is_healthy("akshare_fund"):
                logger.info("Fetching fund list from AKShare")
                frame = self.akshare.fetch_fund_list_em()
                if not frame.empty:
                    _health_manager.record_success("akshare_fund")
                    return frame
                _health_manager.record_failure("akshare_fund", "EmptyData")
        except Exception as exc:
            error_type = type(exc).__name__
            _health_manager.record_failure("akshare_fund", error_type)
            logger.warning("AKShare fund list failed: error_type=%s", error_type)

        if self.tushare_token and _health_manager.is_healthy("tushare_fund"):
            try:
                logger.info("Falling back to Tushare fund list")
                frame = self.tushare.fetch_fund_list()
                if not frame.empty:
                    _health_manager.record_success("tushare_fund")
                    return frame
                _health_manager.record_failure("tushare_fund", "EmptyData")
            except Exception as exc:
                error_type = type(exc).__name__
                _health_manager.record_failure("tushare_fund", error_type)
                logger.warning("Tushare fund list failed: error_type=%s", error_type)

        raise DataSourceUnavailable("No healthy fund list source returned data")

    def fetch_fund_info_em(self, fund_code: str) -> FundDataFrame:
        """Return one fund's AKShare information using a stable exact-code cache."""

        normalized_code = _normalize_fund_code(fund_code)

        @cached(ttl=1800, key_func=_fund_info_cache_key)
        def _fetch(code: str) -> FundDataFrame:
            try:
                if _health_manager.is_healthy("akshare_fund"):
                    frame = self.akshare.fetch_fund_info_em(code)
                    if not frame.empty:
                        _health_manager.record_success("akshare_fund")
                        return frame
                    _health_manager.record_failure("akshare_fund", "EmptyData")
            except Exception as exc:
                _health_manager.record_failure("akshare_fund", type(exc).__name__)
            return pd.DataFrame()

        return _fetch(normalized_code)

    def fetch_fund_nav_em(self, fund_code: str) -> FundDataFrame:
        """Return one fund's NAV history using a stable exact-code cache."""

        normalized_code = _normalize_fund_code(fund_code)

        @cached(ttl=300, key_func=_fund_nav_cache_key)
        def _fetch(code: str) -> FundDataFrame:
            try:
                if _health_manager.is_healthy("akshare_fund"):
                    frame = self.akshare.fetch_fund_nav_em(code)
                    if not frame.empty:
                        _health_manager.record_success("akshare_fund")
                        return frame
                    _health_manager.record_failure("akshare_fund", "EmptyData")
            except Exception as exc:
                _health_manager.record_failure("akshare_fund", type(exc).__name__)
            return pd.DataFrame()

        return _fetch(normalized_code)

    def get_health_status(self) -> dict[str, HealthStatus]:
        """Return bounded health snapshots for both configured provider slots."""

        return {
            "akshare_fund": _health_manager.get_health_status("akshare_fund"),
            "tushare_fund": _health_manager.get_health_status("tushare_fund"),
        }
