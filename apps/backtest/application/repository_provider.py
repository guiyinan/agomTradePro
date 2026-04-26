"""Repository provider for backtest application orchestration."""

from __future__ import annotations

from apps.backtest.infrastructure.providers import DjangoBacktestRepository


def get_backtest_repository() -> DjangoBacktestRepository:
    """Return the configured backtest repository implementation."""

    return DjangoBacktestRepository()
