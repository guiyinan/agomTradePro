import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from apps.account.application.manual_trade_sync import (
    BrokerTradeImportResult,
    ManualTradeImportUseCase,
)
from apps.account.infrastructure.models import (
    AssetMetadataModel,
    PortfolioModel,
    PositionModel,
    TransactionModel,
)
from apps.account.infrastructure.repositories import PortfolioApiRepository
from apps.backtest.application.decision_replay import (
    DecisionReplayBacktestRequest,
    DecisionReplayBacktestUseCase,
    DecisionReplayComparisonRequest,
    DecisionReplayComparisonUseCase,
)
from apps.data_center.infrastructure.models import PriceBarModel
from apps.decision_rhythm.infrastructure.models import (
    DecisionExecutionLinkModel,
    UnifiedRecommendationModel,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel


def _csv(rows: list[str]) -> bytes:
    header = "traded_at,action,asset_code,shares,price,external_trade_id,notes\n"
    return (header + "\n".join(rows) + "\n").encode("utf-8")


def _confirm_excluded(
    use_case: ManualTradeImportUseCase,
    *,
    user_id: int,
    portfolio_id: int,
    broker_name: str,
    filename: str,
    content: bytes,
) -> BrokerTradeImportResult:
    """Use a real preview before explicitly projecting an excluded fact set."""
    preview = use_case.preview(
        user_id=user_id,
        portfolio_id=portfolio_id,
        broker_name=broker_name,
        filename=filename,
        content=content,
    )
    assert preview.expected_fact_set_fingerprint is not None
    assert preview.expected_balance_fingerprint is not None
    return use_case.confirm(
        user_id=user_id,
        portfolio_id=portfolio_id,
        broker_name=broker_name,
        filename=filename,
        content=content,
        baseline_decision="excluded",
        expected_fact_set_fingerprint=preview.expected_fact_set_fingerprint,
        expected_balance_fingerprint=preview.expected_balance_fingerprint,
    )


@pytest.fixture
def owner_portfolio():
    user = User.objects.create_user(username="manual-sync-user")
    portfolio = PortfolioModel.objects.create(user=user, name="实盘")
    return user, portfolio


@pytest.mark.django_db
def test_import_broker_trades_syncs_positions_and_skips_duplicates(owner_portfolio):
    user, portfolio = owner_portfolio
    AssetMetadataModel.objects.create(
        asset_code="000001.SZ",
        name="Test security",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
    )
    content = _csv(
        [
            "2026-05-20T10:00:00,buy,000001.SZ,100,10.00,t1,first buy",
            "2026-05-21T10:00:00,buy,000001.SZ,100,14.00,t2,second buy",
            "2026-05-22T10:00:00,sell,000001.SZ,50,15.00,t3,partial sell",
        ]
    )

    use_case = ManualTradeImportUseCase()
    result = _confirm_excluded(
        use_case,
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

    duplicate = use_case.confirm(
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name="demo",
        filename="trades.csv",
        content=content,
    )
    assert duplicate.imported_rows == 0
    assert duplicate.skipped_rows == 3
    assert TransactionModel.objects.filter(portfolio=portfolio).count() == 3


@pytest.mark.parametrize(
    ("target_external_trade_id", "target_action"),
    [
        ("buy-source", "buy"),
        ("sell-partial", "sell"),
        ("sell-full", "sell"),
    ],
    ids=["buy-source", "partial-sell", "full-sell"],
)
@pytest.mark.django_db
def test_manual_import_preserves_source_instants_and_replay(
    owner_portfolio,
    target_external_trade_id: str,
    target_action: str,
    record_property,
):
    user, portfolio = owner_portfolio
    AssetMetadataModel.objects.create(
        asset_code="000001.SZ",
        name="Test security",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
    )
    account_id = PortfolioApiRepository().ensure_real_account(portfolio)

    source_rows = [
        (
            "buy-source",
            "buy",
            datetime.fromisoformat("2020-05-20T10:00:00.123456+08:00"),
        ),
        (
            "sell-partial",
            "sell",
            datetime.fromisoformat("2020-05-21T11:22:33.654321+08:00"),
        ),
        (
            "sell-full",
            "sell",
            datetime.fromisoformat("2020-05-22T12:34:56.987654+08:00"),
        ),
    ]
    content = _csv(
        [
            f"{source_rows[0][2].isoformat()},buy,000001.SZ,100,10.00,buy-source,buy import",
            f"{source_rows[1][2].isoformat()},sell,000001.SZ,40,11.00,sell-partial,partial",
            f"{source_rows[2][2].isoformat()},sell,000001.SZ,60,12.00,sell-full,full",
        ]
    )

    import_started = timezone.now()
    use_case = ManualTradeImportUseCase()
    result = _confirm_excluded(
        use_case,
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name="demo",
        filename="source-times.csv",
        content=content,
    )
    import_finished = timezone.now()

    transactions = {
        row.external_trade_id: row
        for row in TransactionModel._default_manager.filter(portfolio=portfolio)
    }
    trades = list(SimulatedTradeModel._default_manager.filter(account_id=account_id).order_by("id"))
    trades_by_external_trade_id = {
        source_rows[index][0]: trade
        for index, trade in enumerate(trades)
        if index < len(source_rows)
    }
    source_by_external_trade_id = {
        external_trade_id: source_time for external_trade_id, _, source_time in source_rows
    }
    observations = []
    for external_trade_id, action, source_time in source_rows:
        transaction = transactions.get(external_trade_id)
        trade = trades_by_external_trade_id.get(external_trade_id)
        observations.append(
            {
                "external_trade_id": external_trade_id,
                "source_action": action,
                "source_traded_at": source_time,
                "transaction": (
                    None
                    if transaction is None
                    else {
                        "action": transaction.action,
                        "traded_at": transaction.traded_at,
                        "created_at": transaction.created_at,
                    }
                ),
                "simulated_trade": (
                    None
                    if trade is None
                    else {
                        "action": trade.action,
                        "execution_time": trade.execution_time,
                        "created_at": trade.created_at,
                    }
                ),
            }
        )
    record_property(
        "manual_fill_time_observations",
        json.dumps(
            {
                "target_external_trade_id": target_external_trade_id,
                "target_action": target_action,
                "import_started": import_started,
                "import_finished": import_finished,
                "result": {
                    "imported_rows": result.imported_rows,
                    "skipped_rows": result.skipped_rows,
                    "error_rows": result.error_rows,
                },
                "rows": observations,
            },
            default=str,
            sort_keys=True,
        ),
    )

    target_trade = trades_by_external_trade_id.get(target_external_trade_id)
    target_source_time = source_by_external_trade_id[target_external_trade_id]
    target_execution_time = target_trade.execution_time if target_trade is not None else None
    assert target_execution_time == target_source_time, (
        f"{target_action} mirror {target_external_trade_id} must retain its "
        f"aware source instant; observed {target_execution_time!r}, "
        f"expected {target_source_time!r}"
    )

    # Counts, created-at bounds, and replay checks follow the timestamp assertion.
    assert result.imported_rows == 3
    assert result.skipped_rows == 0
    assert all(source_time < import_started for _, _, source_time in source_rows)
    assert all(
        source_time.utcoffset() == timedelta(hours=8) and source_time.microsecond
        for _, _, source_time in source_rows
    )
    assert len(transactions) == 3
    assert len(trades) == 3

    for trade, (external_trade_id, action, source_time) in zip(trades, source_rows, strict=True):
        transaction = transactions[external_trade_id]
        assert transaction.action == action
        assert transaction.traded_at == source_time
        assert transaction.traded_at.microsecond == source_time.microsecond
        assert transaction.created_at > source_time
        assert import_started <= transaction.created_at <= import_finished
        assert trade.action == action
        assert trade.execution_time == source_time
        assert trade.execution_time.microsecond == source_time.microsecond
        assert trade.created_at > source_time
        assert import_started <= trade.created_at <= import_finished

    transaction_snapshot = {
        external_trade_id: (row.traded_at, row.created_at)
        for external_trade_id, row in transactions.items()
    }
    trade_snapshot = [(row.pk, row.execution_time, row.created_at) for row in trades]
    replay = use_case.confirm(
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name="demo",
        filename="source-times.csv",
        content=content,
    )
    assert replay.imported_rows == 0
    assert replay.skipped_rows == 3
    assert TransactionModel._default_manager.filter(portfolio=portfolio).count() == 3
    assert SimulatedTradeModel._default_manager.filter(account_id=account_id).count() == 3
    assert {
        row.external_trade_id: (row.traded_at, row.created_at)
        for row in TransactionModel._default_manager.filter(portfolio=portfolio)
    } == transaction_snapshot
    assert [
        (row.pk, row.execution_time, row.created_at)
        for row in SimulatedTradeModel._default_manager.filter(account_id=account_id).order_by("id")
    ] == trade_snapshot


@pytest.mark.django_db
def test_transaction_failure_rolls_back_position_side_effects(
    owner_portfolio,
    monkeypatch,
):
    """An atomic source-fact write failure leaves neither a partial fact nor holdings."""

    user, portfolio = owner_portfolio
    transaction_manager_class = type(TransactionModel._default_manager)
    original_create = transaction_manager_class.create
    attempted_external_ids = []

    def _fail_after_fact_insert(manager, **kwargs):
        created = original_create(manager, **kwargs)
        if manager.model is TransactionModel and kwargs.get("external_trade_id") == "t9":
            attempted_external_ids.append("t9")
            raise RuntimeError("source-fact write aborted after insert")
        return created

    monkeypatch.setattr(
        transaction_manager_class,
        "create",
        _fail_after_fact_insert,
    )
    use_case = ManualTradeImportUseCase()
    result = _confirm_excluded(
        use_case,
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name="demo",
        filename="rollback.csv",
        content=_csv(["2026-05-20T10:00:00,buy,000009.SZ,100,10.00,t9,rollback"]),
    )

    assert attempted_external_ids == ["t9"]
    account_id = PortfolioApiRepository().ensure_real_account(portfolio)
    assert result.imported_rows == 0
    assert result.facts_saved_count == 0
    assert result.error_rows == 2
    assert result.reconciliation_error_code == "BROKER_FACT_SET_EMPTY"
    assert result.skipped_rows == 0
    assert result.duplicate_facts_reused_count == 0
    assert result.projected_fact_count == 0
    assert result.pending_fact_count == 0
    assert result.rows[0]["status"] == "fact_persistence_failed"
    assert any(
        error.get("error_code") == "broker_fact_persistence_failed" for error in result.errors
    )
    assert not TransactionModel.objects.filter(
        portfolio=portfolio,
        external_trade_id="t9",
    ).exists()
    assert not TransactionModel.objects.filter(portfolio=portfolio).exists()
    assert (
        PortfolioApiRepository().get_unified_position_for_account_asset(
            account_id=account_id,
            asset_code="000009.SZ",
        )
        is None
    )
    assert not PositionModel.objects.filter(
        portfolio=portfolio,
        asset_code="000009.SZ",
    ).exists()
    assert not SimulatedTradeModel.objects.filter(account_id=account_id).exists()


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
def test_preview_rejects_unbounded_parser_rows(owner_portfolio):
    user, portfolio = owner_portfolio

    class OversizedParser:
        def parse(self, *, content: bytes, filename: str):
            return [{} for _ in range(5001)]

    use_case = ManualTradeImportUseCase(parser=OversizedParser())

    with pytest.raises(ValueError, match="cannot exceed 5000 rows"):
        use_case.preview(
            user_id=user.id,
            portfolio_id=portfolio.id,
            broker_name="demo",
            filename="large.csv",
            content=b"ignored",
        )


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


@pytest.mark.django_db
def test_decision_replay_comparison_merges_all_fixed_branches(owner_portfolio):
    user, portfolio = owner_portfolio
    ManualTradeImportUseCase().confirm(
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name="demo",
        filename="comparison.csv",
        content=_csv(["2026-05-20T10:00:00,buy,000001.SZ,100,10.00,t1,first buy"]),
    )

    response = DecisionReplayComparisonUseCase().execute(
        DecisionReplayComparisonRequest(
            user_id=user.id,
            portfolio_id=portfolio.id,
            start_date=date(2026, 5, 19),
            end_date=date(2026, 5, 25),
            initial_capital=Decimal("10000"),
        )
    )

    assert response.success
    assert [row["branch_type"] for row in response.branches] == [
        "actual",
        "no_action",
        "system_plan",
        "delayed_1d",
    ]
    assert response.equity_curve[0]["date"] == "2026-05-19"
    assert {
        "actual",
        "no_action",
        "system_plan",
        "delayed_1d",
    } <= response.equity_curve[-1].keys()
    assert user.backtests.count() == 4


@pytest.mark.django_db
def test_tui_csv_import_preview_is_owner_scoped(client, owner_portfolio):
    user, portfolio = owner_portfolio
    client.force_login(user)
    response = client.post(
        "/api/account/tui/broker-trades/preview/",
        data={
            "portfolio_id": portfolio.id,
            "broker_name": "tui",
            "file": _csv(["2026-05-20T10:00:00,buy,000001.SZ,100,10.00,t1,preview"]).decode(
                "utf-8"
            ),
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["valid_rows"] == 1
    assert response.json()["rows"][0]["asset_code"] == "000001.SZ"

    other_user = User.objects.create_user(username="other-manual-sync-user")
    other_portfolio = PortfolioModel.objects.create(user=other_user, name="其他组合")
    forbidden = client.post(
        "/api/account/tui/broker-trades/preview/",
        data={
            "portfolio_id": other_portfolio.id,
            "broker_name": "tui",
            "file": _csv(["2026-05-20T10:00:00,buy,000001.SZ,100,10.00,t1,forbidden"]).decode(
                "utf-8"
            ),
        },
        content_type="application/json",
    )

    assert forbidden.status_code == 403


@pytest.mark.django_db
def test_decision_replay_values_open_positions_with_data_center_prices(owner_portfolio):
    user, portfolio = owner_portfolio
    ManualTradeImportUseCase().confirm(
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name="demo",
        filename="replay-market.csv",
        content=_csv(["2026-05-20T10:00:00,buy,000001.SZ,100,10.00,t1,first buy"]),
    )
    PriceBarModel.objects.bulk_create(
        [
            PriceBarModel(
                asset_code="000001.SZ",
                bar_date=date(2026, 5, 20),
                freq="1d",
                adjustment="none",
                open=Decimal("10.00"),
                high=Decimal("10.20"),
                low=Decimal("9.90"),
                close=Decimal("10.00"),
                source="test-data-center",
            ),
            PriceBarModel(
                asset_code="000001.SZ",
                bar_date=date(2026, 5, 25),
                freq="1d",
                adjustment="none",
                open=Decimal("11.80"),
                high=Decimal("12.20"),
                low=Decimal("11.70"),
                close=Decimal("12.00"),
                source="test-data-center",
            ),
        ]
    )

    response = DecisionReplayBacktestUseCase().execute(
        DecisionReplayBacktestRequest(
            user_id=user.id,
            portfolio_id=portfolio.id,
            start_date=date(2026, 5, 19),
            end_date=date(2026, 5, 25),
            branch_type="actual",
            initial_capital=Decimal("10000"),
        )
    )

    assert response.success
    backtest = user.backtests.get(id=response.backtest_id)
    assert backtest.final_capital == Decimal("10200.00")
    assert backtest.equity_curve[-1]["value"] == 10200.0
    assert "no data_center close prices" not in " ".join(backtest.warnings)
