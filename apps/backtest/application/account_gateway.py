"""Register Backtest repository access for Account consumers."""

from __future__ import annotations

from apps.account.application.business_provider_gateway import (
    register_backtest_repository_factory,
)

from . import repository_provider


def register_backtest_account_gateway() -> None:
    """Register the owning Backtest repository factory."""

    register_backtest_repository_factory(repository_provider.get_backtest_repository)


__all__ = ["register_backtest_account_gateway"]
