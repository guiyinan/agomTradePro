from apps.account.infrastructure.models import (
    CapitalFlowModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
    TransactionModel,
)
from core.integration.account_ledger import (
    get_account_position_model,
    get_account_transaction_model,
    get_capital_flow_model,
    get_portfolio_model,
    get_portfolio_observer_grant_model,
)


def test_account_ledger_bridge_exposes_legacy_account_models():
    assert get_portfolio_observer_grant_model() is PortfolioObserverGrantModel
    assert get_capital_flow_model() is CapitalFlowModel
    assert get_portfolio_model() is PortfolioModel
    assert get_account_position_model() is PositionModel
    assert get_account_transaction_model() is TransactionModel
