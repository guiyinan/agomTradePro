"""Regression coverage for cash and cost evidence at performance boundaries."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest

from apps.share.application import interface_services as share_interface_services
from apps.share.domain.interfaces import (
    ShareOwnedAccountSnapshot,
    ShareOwnedPositionSnapshot,
)
from apps.simulated_trading.application import interface_services as simulated_interface_services
from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
from apps.simulated_trading.application.daily_net_value_service import DailyNetValueService
from apps.simulated_trading.application.facade import SimulatedTradingFacade
from apps.simulated_trading.application.performance_calculator import PerformanceCalculator
from apps.simulated_trading.application.performance_use_cases import (
    GetAccountPerformanceReportUseCase,
    GetAccountValuationSnapshotUseCase,
)
from apps.simulated_trading.domain.entities import (
    AccountCashReconciliationStatus,
    AccountType,
    OrderStatus,
    SimulatedAccount,
    SimulatedTrade,
    TradeAction,
)
from apps.simulated_trading.interface import _view_helpers
from core.exceptions import BusinessLogicError


def _account(
    account_type: AccountType = AccountType.SIMULATED,
    *,
    cash_known: bool | None = None,
) -> SimulatedAccount:
    """Build an account with conspicuous numeric cash placeholders."""

    status = (
        AccountCashReconciliationStatus.SIMULATED_LEDGER
        if account_type is AccountType.SIMULATED
        else AccountCashReconciliationStatus.QUANTITY_ONLY
    )
    known = account_type is AccountType.SIMULATED if cash_known is None else cash_known
    return SimulatedAccount(
        account_id=41,
        account_name="evidence boundary",
        account_type=account_type,
        initial_capital=100_000.0,
        current_cash=12_345.0,
        current_market_value=67_890.0,
        total_value=80_235.0,
        start_date=date(2026, 1, 1),
        cash_known=known,
        cash_reconciliation_status=status,
        total_return=18.0,
        win_rate=80.0,
        winning_trades=4,
    )


def _trade(
    *,
    cost_basis_known: bool | None,
    fee_amounts_known: bool | None,
    realized_pnl: float | None = 5.0,
) -> SimulatedTrade:
    """Build one executed SELL whose numeric PnL must follow its flags."""

    return SimulatedTrade(
        trade_id=1,
        account_id=41,
        asset_code="600000.SH",
        asset_name="浦发银行",
        asset_type="equity",
        action=TradeAction.SELL,
        quantity=1.0,
        price=10.0,
        amount=10.0,
        order_date=date(2026, 1, 2),
        execution_date=date(2026, 1, 2),
        execution_time=datetime(2026, 1, 2, tzinfo=UTC),
        realized_pnl=realized_pnl,
        realized_pnl_pct=50.0 if realized_pnl is not None else None,
        status=OrderStatus.EXECUTED,
        cost_basis_known=cost_basis_known,
        fee_amounts_known=fee_amounts_known,
    )


class _AccountRepository:
    def __init__(self, account: SimulatedAccount) -> None:
        self.account = account
        self.save_calls = 0

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        return self.account if account_id == self.account.account_id else None

    def get_active_accounts(self) -> list[SimulatedAccount]:
        return [self.account]

    def user_owns_account(self, account_id: int, user_id: int) -> bool:
        return account_id == self.account.account_id

    def save(self, account: SimulatedAccount, user_id: int | None = None) -> int:
        self.save_calls += 1
        self.account = account
        return account.account_id


class _PositionRepository:
    def __init__(self, positions: list[Any] | None = None) -> None:
        self.positions = positions or []
        self.read_calls = 0

    def get_by_account(self, account_id: int) -> list[Any]:
        self.read_calls += 1
        return self.positions

    def get_position(self, account_id: int, asset_code: str) -> Any | None:
        return None


class _TradeRepository:
    def __init__(self, trades: list[SimulatedTrade]) -> None:
        self.trades = trades
        self.read_calls = 0

    def get_by_account(self, account_id: int) -> list[SimulatedTrade]:
        self.read_calls += 1
        return self.trades

    def get_by_date_range(
        self,
        account_id: int,
        start: date,
        end: date,
    ) -> list[SimulatedTrade]:
        self.read_calls += 1
        return self.trades

    def count_by_execution_date(self, account_id: int, execution_date: date) -> int:
        return len(self.trades)


class _DailyNetValueRepository:
    def __init__(self) -> None:
        self.upsert_calls = 0

    def upsert_daily_record(self, account_id: int, record_date: date, payload: Any) -> None:
        self.upsert_calls += 1

    def get_latest_record_before(self, account_id: int, current_date: date) -> None:
        return None

    def get_max_net_value_before(self, account_id: int, before_date: date) -> None:
        return None

    def list_daily_records(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[Any]:
        return []


class _PriceProvider:
    def get_price(self, asset_code: str, trade_date: date) -> float | None:
        return 10.0

    def require_price(self, asset_code: str, trade_date: date) -> float:
        return 10.0


def test_facade_refuses_unknown_cash_and_hides_dependent_account_totals() -> None:
    account_repo = _AccountRepository(_account(AccountType.REAL, cash_known=False))
    position_repo = _PositionRepository(
        [
            type(
                "PositionRead",
                (),
                {"valuation_known": True, "market_value": 67_890.0, "quantity": 1},
            )()
        ]
    )
    facade = SimulatedTradingFacade(account_repo, position_repo)
    facade._get_active_strategy_binding = lambda account_id: None

    summary = facade.get_account_summary(41)

    assert summary is not None
    assert summary.current_cash is None
    assert summary.market_value == pytest.approx(67_890)
    assert summary.total_value is None
    assert summary.cash_known is False
    assert summary.cash_reconciliation_status == "quantity_only"
    with pytest.raises(BusinessLogicError) as error:
        facade.get_cash(41)
    assert error.value.code == "ACCOUNT_CASH_UNKNOWN"


def test_daily_net_value_blocks_unknown_cash_before_any_snapshot_or_account_write() -> None:
    account_repo = _AccountRepository(_account(AccountType.REAL, cash_known=False))
    position_repo = _PositionRepository()
    trade_repo = _TradeRepository([])
    daily_repo = _DailyNetValueRepository()
    service = DailyNetValueService(account_repo, position_repo, trade_repo, daily_repo)

    result = service.record_and_update_performance(41, date(2026, 1, 3))

    assert result["outcome"] == "blocked"
    assert result["reason_code"] == "ACCOUNT_CASH_UNKNOWN"
    assert result["stored"] == 0
    assert position_repo.read_calls == 0
    assert daily_repo.upsert_calls == 0
    assert account_repo.save_calls == 0


@pytest.mark.parametrize(
    ("cost_basis_known", "fee_amounts_known", "reason_code"),
    [
        (None, True, "TRADE_COST_KNOWLEDGE_UNKNOWN"),
        (True, None, "TRADE_COST_KNOWLEDGE_UNKNOWN"),
        (False, True, "TRADE_COST_KNOWLEDGE_PARTIAL"),
        (True, False, "TRADE_COST_KNOWLEDGE_PARTIAL"),
    ],
)
def test_daily_net_value_blocks_incomplete_sell_cost_before_snapshot_write(
    cost_basis_known: bool | None,
    fee_amounts_known: bool | None,
    reason_code: str,
) -> None:
    account_repo = _AccountRepository(_account())
    position_repo = _PositionRepository()
    trade_repo = _TradeRepository(
        [_trade(cost_basis_known=cost_basis_known, fee_amounts_known=fee_amounts_known)]
    )
    daily_repo = _DailyNetValueRepository()
    service = DailyNetValueService(account_repo, position_repo, trade_repo, daily_repo)

    result = service.record_and_update_performance(41, date(2026, 1, 3))

    assert result["outcome"] == "blocked"
    assert result["reason_code"] == reason_code
    assert result["stored"] == 0
    assert position_repo.read_calls == 0
    assert daily_repo.upsert_calls == 0
    assert account_repo.save_calls == 0


def test_auto_engine_does_not_report_blocked_daily_snapshot_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BlockedDailyNetValueService:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def record_and_update_performance(
            self,
            account_id: int,
            record_date: date,
        ) -> dict[str, Any]:
            return {"outcome": "blocked", "reason_code": "ACCOUNT_CASH_UNKNOWN"}

    monkeypatch.setattr(
        "apps.simulated_trading.application.daily_net_value_service.DailyNetValueService",
        _BlockedDailyNetValueService,
    )
    engine = object.__new__(AutoTradingEngine)
    engine.account_repo = object()
    engine.position_repo = object()
    engine.trade_repo = object()

    assert engine._update_account_performance(41, date(2026, 1, 3)) is False


@pytest.mark.parametrize(
    ("cost_basis_known", "fee_amounts_known", "reason_code"),
    [
        (None, True, "TRADE_COST_KNOWLEDGE_UNKNOWN"),
        (True, None, "TRADE_COST_KNOWLEDGE_UNKNOWN"),
        (False, True, "TRADE_COST_KNOWLEDGE_PARTIAL"),
        (True, False, "TRADE_COST_KNOWLEDGE_PARTIAL"),
    ],
)
def test_trade_win_rate_and_sharpe_refuse_numeric_pnl_with_incomplete_cost_flags(
    cost_basis_known: bool | None,
    fee_amounts_known: bool | None,
    reason_code: str,
) -> None:
    account = _account()
    repository = _TradeRepository(
        [
            _trade(
                cost_basis_known=cost_basis_known,
                fee_amounts_known=fee_amounts_known,
                realized_pnl=50.0,
            )
        ]
    )
    calculator = PerformanceCalculator(
        account_repo=_AccountRepository(account),
        trade_repo=repository,
        price_provider=_PriceProvider(),
    )

    for calculate in (calculator._calculate_win_rate, calculator._calculate_sharpe_ratio):
        with pytest.raises(BusinessLogicError) as error:
            calculate(account, date(2026, 1, 3))
        assert error.value.code == reason_code


def test_performance_report_returns_null_trade_metrics_for_unknown_cost_rows() -> None:
    class _ReportAccountRepository:
        def get_by_id(self, account_id: int) -> dict[str, Any]:
            return {"initial_capital": 100.0, "account_type": "simulated"}

    class _DailyRepository:
        def list_range(self, account_id: int, start_date: date, end_date: date) -> list[Any]:
            return []

    class _CashFlowRepository:
        def list_for_account(
            self,
            account_id: int,
            start_date: date | None = None,
            end_date: date | None = None,
        ) -> list[Any]:
            return []

    class _BenchmarkRepository:
        def list_active(self, account_id: int) -> list[Any]:
            return []

    class _MarketDataRepository:
        pass

    class _TradeHistoryRepository:
        def list_closed_trades(
            self,
            account_id: int,
            start_date: date | None = None,
            end_date: date | None = None,
        ) -> list[dict[str, Any]]:
            return [
                {
                    "realized_pnl": 50.0,
                    "cost_basis_known": None,
                    "fee_amounts_known": True,
                }
            ]

    use_case = GetAccountPerformanceReportUseCase(
        _ReportAccountRepository(),
        _DailyRepository(),
        _CashFlowRepository(),
        _BenchmarkRepository(),
        _MarketDataRepository(),
        _TradeHistoryRepository(),
    )

    report = use_case.execute(41, date(2026, 1, 1), date(2026, 1, 3))

    assert report.trade_stats.win_rate is None
    assert report.trade_stats.profit_factor is None
    assert report.trade_stats.total_closed_trades == 1
    assert any("成本或费用知识未知" in warning for warning in report.coverage.warnings)


def test_valuation_snapshot_does_not_fallback_to_unknown_current_cash() -> None:
    class _AccountRepository:
        def get_by_id(self, account_id: int) -> dict[str, Any]:
            return {"current_cash": 12_345.0, "cash_known": False}

    class _SnapshotRepository:
        def get_for_date(self, account_id: int, as_of_date: date) -> list[Any]:
            return []

    class _DailyRepository:
        def get_record_for_date(self, account_id: int, record_date: date) -> None:
            return None

    use_case = GetAccountValuationSnapshotUseCase(
        _AccountRepository(),
        _SnapshotRepository(),
        _DailyRepository(),
    )

    with pytest.raises(BusinessLogicError) as error:
        use_case.execute(41, date(2026, 1, 2))

    assert error.value.code == "ACCOUNT_CASH_UNKNOWN"

    class _HistoricalDailyRepository:
        def get_record_for_date(self, account_id: int, record_date: date) -> dict[str, float]:
            return {"cash": 6_543.0}

    historical_use_case = GetAccountValuationSnapshotUseCase(
        _AccountRepository(),
        _SnapshotRepository(),
        _HistoricalDailyRepository(),
    )
    historical = historical_use_case.execute(41, date(2026, 1, 2))

    assert historical.account_summary.cash == pytest.approx(6_543.0)


def test_nested_account_payload_masks_unknown_valuation_and_trade_aggregates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _account()
    unknown_position = type("PositionRead", (), {"valuation_known": False})()
    repository = _PositionRepository([unknown_position])
    monkeypatch.setattr(
        _view_helpers.simulated_interface_services,
        "get_simulated_position_repository",
        lambda: repository,
    )
    monkeypatch.setattr(
        _view_helpers.simulated_interface_services,
        "has_complete_closed_trade_costs",
        lambda account_id: False,
    )

    payload = _view_helpers._account_payload(account)

    assert payload["current_market_value"] is None
    assert payload["total_value"] is None
    assert payload["valuation_status"] == "unknown"
    assert payload["win_rate"] is None
    assert payload["winning_trades"] is None
    assert payload["realized_trade_metrics_known"] is False


def test_share_snapshot_preserves_known_quantity_but_hides_unknown_money_and_pnl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ShareRepository:
        def get_share_link_by_id(self, share_link_id: int) -> Any:
            return type("ShareLink", (), {"id": 9, "owner_id": 7, "account_id": 41})()

        def get_owned_account_for_snapshot(
            self,
            *,
            owner_id: int,
            account_id: int,
        ) -> ShareOwnedAccountSnapshot:
            return ShareOwnedAccountSnapshot(
                id=account_id,
                account_name="shared quantity-only account",
                account_type="real",
                start_date=date(2026, 1, 1),
                total_value=80_235.0,
                current_market_value=67_890.0,
                current_cash=12_345.0,
                total_return=18.0,
                annual_return=12.0,
                max_drawdown=3.0,
                sharpe_ratio=1.2,
                win_rate=80.0,
                total_trades=5,
                cash_known=False,
                cash_reconciliation_status="quantity_only",
                realized_trade_metrics_known=False,
            )

        def list_owned_account_positions_for_snapshot(
            self,
            *,
            owner_id: int,
            account_id: int,
        ) -> list[ShareOwnedPositionSnapshot]:
            return [
                ShareOwnedPositionSnapshot(
                    asset_code="600000.SH",
                    asset_name="浦发银行",
                    asset_type="equity",
                    quantity=10,
                    avg_cost=10,
                    current_price=12,
                    market_value=120,
                    unrealized_pnl=20,
                    unrealized_pnl_pct=20,
                    entry_reason="source fact",
                    invalidation_description="",
                    valuation_known=True,
                    cost_basis_known=None,
                )
            ]

        def list_owned_account_trades_for_snapshot(
            self,
            *,
            owner_id: int,
            account_id: int,
            limit: int,
        ) -> list[Any]:
            return []

        def list_decision_requests_for_account_assets(
            self,
            *,
            account_id: int,
            asset_codes: set[str],
        ) -> list[Any]:
            return []

    captured: dict[str, Any] = {}

    class _SnapshotUseCases:
        def create_snapshot(self, **payload: Any) -> int:
            captured.update(payload)
            return 77

    monkeypatch.setattr(share_interface_services, "_repo", lambda: _ShareRepository())
    monkeypatch.setattr(
        share_interface_services,
        "ShareSnapshotUseCases",
        _SnapshotUseCases,
    )

    snapshot_id = share_interface_services.build_share_snapshot_from_account(share_link_id=9)

    assert snapshot_id == 77
    assert captured["summary_payload"]["total_assets"] is None
    assert captured["summary_payload"]["cash_balance"] is None
    assert captured["summary_payload"]["cash_reconciliation_status"] == "quantity_only"
    assert captured["performance_payload"]["win_rate"] is None
    position = captured["positions_payload"]["items"][0]
    assert position["quantity"] == 10.0
    assert position["market_value"] == 120.0
    assert position["avg_cost"] is None
    assert position["pnl"] is None


def test_admin_summary_does_not_sum_unverified_account_or_trade_amounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _account(AccountType.REAL, cash_known=False)

    class _AdminAccountRepository:
        def get_active_accounts(self) -> list[SimulatedAccount]:
            return [account]

        def count_active_account_models(self) -> int:
            return 1

    class _AdminPositionRepository:
        def get_by_account(self, account_id: int) -> list[Any]:
            return []

        def count_position_models(self) -> int:
            return 0

    class _AdminTradeRepository:
        def summarize_trade_models_for_date(self, execution_date: date) -> dict[str, int]:
            return {"buy_count": 0, "sell_count": 0}

        def count_trade_models(self) -> int:
            return 0

        def sum_realized_pnl_for_closed_trades(self) -> dict[str, Any]:
            return {
                "realized_pnl": None,
                "known": False,
                "covered_executed_sell_count": 0,
                "executed_sell_count": 1,
            }

    monkeypatch.setattr(
        simulated_interface_services,
        "get_simulated_account_repository",
        lambda: _AdminAccountRepository(),
    )
    monkeypatch.setattr(
        simulated_interface_services,
        "get_simulated_position_repository",
        lambda: _AdminPositionRepository(),
    )
    monkeypatch.setattr(
        simulated_interface_services,
        "get_simulated_trade_repository",
        lambda: _AdminTradeRepository(),
    )

    context = simulated_interface_services.build_admin_dashboard_context()

    assert context["total_capital"] is None
    assert context["total_pnl"] is None
    assert context["total_pnl_known"] is False
    assert context["total_pnl_covered_sell_count"] == 0
    assert context["total_pnl_executed_sell_count"] == 1


def test_daily_net_value_blocks_unknown_position_valuation_before_any_write() -> None:
    account_repo = _AccountRepository(_account())
    unknown_position = type("PositionRead", (), {"valuation_known": False})()
    position_repo = _PositionRepository([unknown_position])
    trade_repo = _TradeRepository([])
    daily_repo = _DailyNetValueRepository()
    service = DailyNetValueService(account_repo, position_repo, trade_repo, daily_repo)

    result = service.record_and_update_performance(41, date(2026, 1, 3))

    assert result["outcome"] == "blocked"
    assert result["reason_code"] == "POSITION_VALUATION_UNKNOWN"
    assert result["requested"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["stored"] == 0
    assert position_repo.read_calls == 1
    assert daily_repo.upsert_calls == 0
    assert account_repo.save_calls == 0


def test_nested_account_payload_hides_sharpe_when_trade_metrics_are_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = replace(
        _account(), total_return=17.0, annual_return=18.0, max_drawdown=9.0, sharpe_ratio=2.5
    )
    monkeypatch.setattr(
        _view_helpers.simulated_interface_services,
        "has_current_position_valuation",
        lambda account_id: True,
    )
    monkeypatch.setattr(
        _view_helpers.simulated_interface_services,
        "has_complete_closed_trade_costs",
        lambda account_id: False,
    )

    payload = _view_helpers._account_payload(account)

    assert payload["current_market_value"] == "67890.0"
    assert payload["total_value"] == "80235.0"
    assert payload["realized_trade_metrics_known"] is False
    assert payload["total_return"] is None
    assert payload["annual_return"] is None
    assert payload["max_drawdown"] is None
    assert payload["sharpe_ratio"] is None
    assert payload["win_rate"] is None
    assert payload["winning_trades"] is None


def test_share_snapshot_hides_performance_when_trade_metrics_are_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ShareRepository:
        def get_share_link_by_id(self, share_link_id: int) -> Any:
            return type("ShareLink", (), {"id": 9, "owner_id": 7, "account_id": 41})()

        def get_owned_account_for_snapshot(
            self,
            *,
            owner_id: int,
            account_id: int,
        ) -> ShareOwnedAccountSnapshot:
            return ShareOwnedAccountSnapshot(
                id=account_id,
                account_name="shared account with unknown trade metrics",
                account_type="simulated",
                start_date=date(2026, 1, 1),
                total_value=80_235.0,
                current_market_value=67_890.0,
                current_cash=12_345.0,
                total_return=18.0,
                annual_return=12.0,
                max_drawdown=3.0,
                sharpe_ratio=1.2,
                win_rate=80.0,
                total_trades=5,
                cash_known=True,
                cash_reconciliation_status="simulated_ledger",
                realized_trade_metrics_known=False,
            )

        def list_owned_account_positions_for_snapshot(
            self,
            *,
            owner_id: int,
            account_id: int,
        ) -> list[ShareOwnedPositionSnapshot]:
            return [
                ShareOwnedPositionSnapshot(
                    asset_code="600000.SH",
                    asset_name="浦发银行",
                    asset_type="equity",
                    quantity=10,
                    avg_cost=10,
                    current_price=12,
                    market_value=120,
                    unrealized_pnl=20,
                    unrealized_pnl_pct=20,
                    entry_reason="source fact",
                    invalidation_description="",
                    valuation_known=True,
                    cost_basis_known=True,
                )
            ]

        def list_owned_account_trades_for_snapshot(
            self,
            *,
            owner_id: int,
            account_id: int,
            limit: int,
        ) -> list[Any]:
            return []

        def list_decision_requests_for_account_assets(
            self,
            *,
            account_id: int,
            asset_codes: set[str],
        ) -> list[Any]:
            return []

    captured: dict[str, Any] = {}

    class _SnapshotUseCases:
        def create_snapshot(self, **payload: Any) -> int:
            captured.update(payload)
            return 77

    monkeypatch.setattr(share_interface_services, "_repo", lambda: _ShareRepository())
    monkeypatch.setattr(
        share_interface_services,
        "ShareSnapshotUseCases",
        _SnapshotUseCases,
    )
    monkeypatch.setattr(share_interface_services, "_build_decision_chain", lambda *args: ([], []))

    snapshot_id = share_interface_services.build_share_snapshot_from_account(share_link_id=9)

    assert snapshot_id == 77
    assert captured["summary_payload"]["total_assets"] == pytest.approx(80_235.0)
    assert captured["summary_payload"]["cash_balance"] == pytest.approx(12_345.0)
    assert captured["performance_payload"]["realized_trade_metrics_known"] is False
    assert captured["performance_payload"]["total_return"] is None
    assert captured["performance_payload"]["annualized_return"] is None
    assert captured["performance_payload"]["max_drawdown"] is None
    assert captured["performance_payload"]["sharpe_ratio"] is None
    assert captured["performance_payload"]["win_rate"] is None
