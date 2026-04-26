"""Bridge helpers for legacy account ledger models."""

from __future__ import annotations


def get_portfolio_observer_grant_model():
    """Return the legacy account observer grant model class."""

    from apps.account.infrastructure.models import PortfolioObserverGrantModel

    return PortfolioObserverGrantModel


def get_capital_flow_model():
    """Return the legacy account capital flow model class."""

    from apps.account.infrastructure.models import CapitalFlowModel

    return CapitalFlowModel


def get_portfolio_model():
    """Return the legacy account portfolio model class."""

    from apps.account.infrastructure.models import PortfolioModel

    return PortfolioModel


def get_account_portfolio_model():
    """Return the legacy account portfolio model class."""

    return get_portfolio_model()


def get_account_position_model():
    """Return the legacy account position model class."""

    from apps.account.infrastructure.models import PositionModel

    return PositionModel


def get_account_transaction_model():
    """Return the legacy account transaction model class."""

    from apps.account.infrastructure.models import TransactionModel

    return TransactionModel
