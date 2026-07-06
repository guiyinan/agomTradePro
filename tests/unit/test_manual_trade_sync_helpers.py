from apps.audit.application.interface_services import build_manual_trade_review_context_payload
from apps.backtest.application.decision_replay import get_manual_trade_sync_repository
from apps.decision_rhythm.application.advisor_services import (
    get_manual_trade_portfolio_id_for_account as get_advisor_manual_trade_portfolio_id,
)
from apps.simulated_trading.application.interface_services import (
    get_manual_trade_portfolio_id_for_account as get_simulated_manual_trade_portfolio_id,
)


def test_get_manual_trade_sync_repository_uses_account_repository_provider(monkeypatch):
    sentinel = object()

    monkeypatch.setattr(
        "apps.account.application.repository_provider.get_manual_trade_sync_repository",
        lambda: sentinel,
    )

    assert get_manual_trade_sync_repository() is sentinel


def test_build_manual_trade_review_context_payload_uses_account_use_case(monkeypatch):
    monkeypatch.setattr(
        "apps.audit.application.interface_services.ManualTradeReviewSummaryUseCase",
        lambda: type(
            "_UseCase",
            (),
            {"execute": staticmethod(lambda *, user_id: {"user_id": user_id, "rows": []})},
        )(),
    )

    assert build_manual_trade_review_context_payload(7) == {"user_id": 7, "rows": []}


def test_manual_trade_portfolio_id_helpers_use_portfolio_repository(monkeypatch):
    class _PortfolioRepository:
        @staticmethod
        def get_portfolio_for_account(account_id):
            return type("_Portfolio", (), {"id": account_id + 100})()

    monkeypatch.setattr(
        "apps.account.application.repository_provider.get_portfolio_api_repository",
        lambda: _PortfolioRepository(),
    )

    assert get_advisor_manual_trade_portfolio_id(3) == 103
    assert get_simulated_manual_trade_portfolio_id(5) == 105

