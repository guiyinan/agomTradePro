from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from apps.account.application.manual_trade_sync import ManualTradeImportUseCase
from apps.account.infrastructure.models import PortfolioModel, TransactionModel
from apps.account.infrastructure.repositories import PortfolioApiRepository
from apps.backtest.application.decision_replay import (
    DecisionReplayBacktestRequest,
    DecisionReplayBacktestUseCase,
)
from apps.decision_rhythm.infrastructure.models import (
    DecisionExecutionLinkModel,
    UnifiedRecommendationModel,
)


def _csv(rows: list[str]) -> bytes:
    header = "traded_at,action,asset_code,shares,price,external_trade_id,notes\n"
    return (header + "\n".join(rows) + "\n").encode("utf-8")


@pytest.fixture
def owner_portfolio():
    user = User.objects.create_user(username="manual-sync-user")
    portfolio = PortfolioModel.objects.create(user=user, name="实盘")
    return user, portfolio


@pytest.mark.django_db
def test_import_broker_trades_syncs_positions_and_skips_duplicates(owner_portfolio):
    user, portfolio = owner_portfolio
    content = _csv(
        [
            "2026-05-20T10:00:00,buy,000001.SZ,100,10.00,t1,first buy",
            "2026-05-21T10:00:00,buy,000001.SZ,100,14.00,t2,second buy",
            "2026-05-22T10:00:00,sell,000001.SZ,50,15.00,t3,partial sell",
        ]
    )

    result = ManualTradeImportUseCase().confirm(
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name="demo",
        filename="trades.csv",
        content=content,
    )

    assert result.imported_rows == 3
    assert TransactionModel.objects.filter(portfolio=portfolio).count() == 3
    account_id = PortfolioApiRepository().ensure_real_account(portfolio)
    unified_position = PortfolioApiRepository().get_unified_position_for_account_asset(
        account_id=account_id,
        asset_code="000001.SZ",
    )
    assert unified_position.quantity == Decimal("150.000000")
    assert unified_position.avg_cost == Decimal("12.0000")

    duplicate = ManualTradeImportUseCase().confirm(
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name="demo",
        filename="trades.csv",
        content=content,
    )
    assert duplicate.imported_rows == 0
    assert duplicate.skipped_rows == 3
    assert TransactionModel.objects.filter(portfolio=portfolio).count() == 3


@pytest.mark.django_db
def test_import_matches_recommendation_and_marks_adopted(owner_portfolio):
    user, portfolio = owner_portfolio
    account_id = PortfolioApiRepository().ensure_real_account(portfolio)
    UnifiedRecommendationModel.objects.create(
        recommendation_id="rec_manual_1",
        account_id=str(account_id),
        security_code="000002.SZ",
        side="BUY",
        composite_score=88.0,
        confidence=0.8,
        suggested_quantity=80,
        entry_price_high=Decimal("9.5000"),
        created_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
    )
    UnifiedRecommendationModel.objects.filter(recommendation_id="rec_manual_1").update(
        created_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC)
    )

    result = ManualTradeImportUseCase().confirm(
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name="demo",
        filename="match.csv",
        content=_csv(["2026-05-20T10:00:00,buy,000002.SZ,100,10.00,t1,matched"]),
    )

    assert result.imported_rows == 1
    recommendation = UnifiedRecommendationModel.objects.get(recommendation_id="rec_manual_1")
    assert recommendation.user_action == "ADOPTED"
    link = DecisionExecutionLinkModel.objects.get(recommendation_id="rec_manual_1")
    assert link.match_method == "auto"
    assert link.transaction_id == TransactionModel.objects.get(asset_code="000002.SZ").id

    response = DecisionReplayBacktestUseCase().execute(
        DecisionReplayBacktestRequest(
            user_id=user.id,
            portfolio_id=portfolio.id,
            start_date=datetime(2026, 5, 19, tzinfo=UTC).date(),
            end_date=datetime(2026, 5, 25, tzinfo=UTC).date(),
            branch_type="system_plan",
            initial_capital=Decimal("10000"),
        )
    )
    assert response.success
    trade = user.backtests.get(id=response.backtest_id).trades[0]
    assert trade["shares"] == 80.0
    assert trade["price"] == 9.5
    assert trade["recommendation_id"] == "rec_manual_1"


@pytest.mark.django_db
def test_preview_reports_row_errors(owner_portfolio):
    user, portfolio = owner_portfolio

    result = ManualTradeImportUseCase().preview(
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name="demo",
        filename="bad.csv",
        content=_csv(["2026-05-20T10:00:00,hold,000001.SZ,100,10.00,t1,bad action"]),
    )

    assert result.valid_rows == 0
    assert result.error_rows == 1
    assert "action must be buy or sell" in result.errors[0]["error"]


@pytest.mark.django_db
def test_decision_replay_no_action_preserves_initial_capital(owner_portfolio):
    user, portfolio = owner_portfolio
    ManualTradeImportUseCase().confirm(
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name="demo",
        filename="replay.csv",
        content=_csv(["2026-05-20T10:00:00,buy,000001.SZ,100,10.00,t1,first buy"]),
    )

    response = DecisionReplayBacktestUseCase().execute(
        DecisionReplayBacktestRequest(
            user_id=user.id,
            portfolio_id=portfolio.id,
            start_date=datetime(2026, 5, 19, tzinfo=UTC).date(),
            end_date=datetime(2026, 5, 25, tzinfo=UTC).date(),
            branch_type="no_action",
            initial_capital=Decimal("10000"),
        )
    )

    assert response.success
    backtest = user.backtests.get(id=response.backtest_id)
    assert backtest.final_capital == Decimal("10000.00")
    assert backtest.trades == []
