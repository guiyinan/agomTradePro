"""Consumer-owned gateways for Account business-provider integrations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_backtest_repository_factory: Callable[[], Any] | None = None
_equity_market_adapter_factory: Callable[[], Any] | None = None
_audit_operation_logger: Callable[..., Any] | None = None
_policy_readiness_checker: Callable[[], bool] | None = None


def register_backtest_repository_factory(factory: Callable[[], Any]) -> None:
    """Register the owning Backtest repository factory."""

    global _backtest_repository_factory
    _backtest_repository_factory = factory


def get_backtest_repository() -> Any:
    """Return the registered Backtest repository."""

    if _backtest_repository_factory is None:
        raise RuntimeError("Backtest repository factory is not registered")
    return _backtest_repository_factory()


def register_equity_market_adapter_factory(factory: Callable[[], Any]) -> None:
    """Register the Equity historical-market adapter factory."""

    global _equity_market_adapter_factory
    _equity_market_adapter_factory = factory


def get_tushare_stock_adapter() -> Any:
    """Return the registered Equity historical-market adapter."""

    if _equity_market_adapter_factory is None:
        raise RuntimeError("Equity market adapter factory is not registered")
    return _equity_market_adapter_factory()


def register_audit_operation_logger(logger: Callable[..., Any]) -> None:
    """Register the owning Audit operation logger."""

    global _audit_operation_logger
    _audit_operation_logger = logger


def log_audit_operation(**payload: Any) -> Any:
    """Persist an operation log through the registered Audit provider."""

    if _audit_operation_logger is None:
        raise RuntimeError("Audit operation logger is not registered")
    return _audit_operation_logger(**payload)


def register_policy_readiness_checker(checker: Callable[[], bool]) -> None:
    """Register the Policy cold-start readiness checker."""

    global _policy_readiness_checker
    _policy_readiness_checker = checker


def authoritative_rss_sources_ready() -> bool:
    """Return whether authoritative Policy RSS sources are ready."""

    if _policy_readiness_checker is None:
        return False
    return _policy_readiness_checker()


__all__ = [
    "authoritative_rss_sources_ready",
    "get_backtest_repository",
    "get_tushare_stock_adapter",
    "log_audit_operation",
    "register_audit_operation_logger",
    "register_backtest_repository_factory",
    "register_equity_market_adapter_factory",
    "register_policy_readiness_checker",
]
