"""App-neutral registry for Portfolio account-access checks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class PortfolioAccountAccessResult(Protocol):
    """Minimal cross-app result required by the Portfolio interface."""

    error: str | None
    status_code: int | None


_account_access_checker: Callable[[object, int, str], PortfolioAccountAccessResult] | None = None


def register_portfolio_account_access_checker(
    checker: Callable[[object, int, str], PortfolioAccountAccessResult],
) -> None:
    """Register the owner-provided account-access checker."""

    global _account_access_checker
    _account_access_checker = checker


def check_portfolio_account_access(
    user: object,
    account_id: int,
    action: str,
) -> PortfolioAccountAccessResult:
    """Check account access, failing closed when no owner is configured."""

    if _account_access_checker is None:
        raise RuntimeError("portfolio account access checker is unavailable")
    return _account_access_checker(user, account_id, action)


__all__ = [
    "PortfolioAccountAccessResult",
    "check_portfolio_account_access",
    "register_portfolio_account_access_checker",
]
