"""T3B simulated-trading interface contracts for ownership and ledger queries."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from apps.simulated_trading.application import interface_services as module
from apps.simulated_trading.domain.entities import TradeAction


def _user(
    user_id: int = 7,
    *,
    authenticated: bool = True,
    superuser: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        is_authenticated=authenticated,
        is_superuser=superuser,
    )


def _account(
    account_id: int = 3,
    *,
    user_id: int = 7,
    account_type: str = "paper",
    total_value: Decimal = Decimal("100"),
) -> SimpleNamespace:
    return SimpleNamespace(
        id=account_id,
        user_id=user_id,
        account_type=account_type,
        total_value=total_value,
        cash_known=True,
    )


def test_account_access_rejects_anonymous_missing_and_cross_user_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All account mutations require authentication, existence, and ownership."""
    repository = SimpleNamespace(get_account_model_by_id=lambda account_id: None)
    monkeypatch.setattr(
        module,
        "get_simulated_account_repository",
        lambda: repository,
    )
    anonymous = module.get_account_access(_user(authenticated=False), 3, "删除")
    assert anonymous.status_code == 401
    assert anonymous.allowed is False
    missing = module.get_account_access(_user(), 3)
    assert missing.status_code == 404

    repository.get_account_model_by_id = lambda account_id: _account(user_id=99)
    forbidden = module.get_account_access(_user(), 3, "修改")
    assert forbidden.status_code == 403
    assert module.can_manage_account(_user(authenticated=False), _account()) is False

    owned = _account()
    repository.get_account_model_by_id = lambda account_id: owned
    allowed = module.get_account_access(_user(), 3)
    assert allowed.allowed is True
    assert allowed.account is owned
    assert module.can_manage_account(_user(user_id=99, superuser=True), owned) is True


def test_account_page_contexts_keep_user_scope_and_empty_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Account/position/trade contexts never fall back to another user's records."""
    position = SimpleNamespace(valuation_known=True)
    trade = SimpleNamespace(
        action=TradeAction.BUY,
        cost_basis_known=True,
        fee_amounts_known=True,
        realized_pnl=None,
        realized_pnl_pct=None,
        current_realized_pnl=None,
        current_realized_pnl_pct=None,
        current_commission=0.0,
        current_transfer_fee=None,
        current_stamp_duty=None,
        current_total_cost=0.0,
        fee_correction_revision=None,
        fee_correction_overlay_applied=False,
    )
    paper = _account(account_id=1, total_value=Decimal("125.50"))
    real = _account(
        account_id=2,
        account_type="real",
        total_value=Decimal("74.50"),
    )
    account_repository = SimpleNamespace(
        list_account_models_for_user=lambda user_id: [paper, real],
        get_account_model_for_user=lambda account_id, user_id: (
            real if account_id == 2 and user_id == 7 else None
        ),
    )
    monkeypatch.setattr(
        module,
        "get_simulated_account_repository",
        lambda: account_repository,
    )
    monkeypatch.setattr(
        module,
        "get_simulated_trading_facade",
        lambda: SimpleNamespace(
            get_active_strategy_summary=lambda account_id: {"account_id": account_id}
        ),
    )
    monkeypatch.setattr(
        module,
        "get_manual_trade_portfolio_id_for_account",
        lambda account_id: 900 + account_id,
    )
    monkeypatch.setattr(
        module,
        "get_simulated_position_repository",
        lambda: SimpleNamespace(
            list_position_models_for_account=lambda account_id, **kwargs: [position]
        ),
    )
    monkeypatch.setattr(
        module,
        "get_simulated_trade_repository",
        lambda: SimpleNamespace(
            get_trade_model_summary_for_account=lambda account_id: {
                "trades": [trade],
                "buy_count": 2,
                "sell_count": 1,
                "total_trade_count": 3,
                "total_realized_pnl": Decimal("3"),
                "total_realized_pnl_known": True,
                "effective_total_realized_pnl": Decimal("3"),
                "effective_total_realized_pnl_known": True,
            }
        ),
    )

    accounts = module.build_my_accounts_context(_user())
    assert accounts["total_assets"] == Decimal("200.00")
    assert paper.manual_trade_portfolio_id is None
    assert real.manual_trade_portfolio_id == 902
    assert module.build_my_positions_context(_user(), 99) is None

    positions = module.build_my_positions_context(_user(), 2)
    assert positions is not None
    assert positions["positions"] == [position]
    assert positions["account_type"] == "真实账户"
    assert positions["position_valuation_known"] is True
    trades = module.build_my_trades_context(_user(), 2)
    assert trades is not None
    assert trades["buy_count"] == 2
    assert trades["total_realized_pnl_known"] is True
    assert trades["trades"] == [trade]
    assert trade.realized_pnl_known is False
    assert trade.realized_pnl_status == "不适用"
    assert module.build_my_trades_context(_user(user_id=8), 2) is None


def test_inspection_notification_context_handles_missing_config_and_persists_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Notification settings distinguish a missing account/config from valid empty recipients."""
    account = _account()
    account_repository = SimpleNamespace(
        get_account_model_for_user=lambda account_id, user_id: (account if user_id == 7 else None)
    )
    inspection_repository = SimpleNamespace(
        get_or_create_notification_config_model=lambda account_id: None,
        update_notification_config=lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(
        module,
        "get_simulated_account_repository",
        lambda: account_repository,
    )
    monkeypatch.setattr(
        module,
        "get_simulated_inspection_repository",
        lambda: inspection_repository,
    )
    assert module.build_inspection_notify_context(_user(user_id=8), 3) is None
    assert module.build_inspection_notify_context(_user(), 3) is None

    config = SimpleNamespace(recipient_emails=["a@example.test", "b@example.test"])
    inspection_repository.get_or_create_notification_config_model = lambda account_id: (
        False,
        config,
    )
    context = module.build_inspection_notify_context(_user(), 3)
    assert context is not None
    assert context["recipient_emails_text"] == "a@example.test\nb@example.test"
    saved = module.save_inspection_notification_config(
        account_id=3,
        is_enabled=True,
        include_owner_email=False,
        notify_on="warning",
        recipient_emails=["a@example.test"],
    )
    assert saved["notify_on"] == "warning"


def test_close_position_and_daily_inspection_expose_remaining_and_proposal_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Position closure serializes the ledger remainder and inspection mode explicitly."""
    remaining_values = iter(
        (
            SimpleNamespace(quantity=Decimal("3")),
            None,
        )
    )
    monkeypatch.setattr(
        module.UnifiedPositionService,
        "default",
        lambda: SimpleNamespace(close_position=lambda **kwargs: next(remaining_values)),
    )
    partial = module.close_account_position(
        account_id=3,
        asset_code="000001.SZ",
        close_shares=Decimal("2"),
    )
    assert partial == {
        "account_id": 3,
        "asset_code": "000001.SZ",
        "closed": False,
        "remaining_quantity": "3",
    }
    full = module.close_account_position(account_id=3, asset_code="000001.SZ")
    assert full["closed"] is True
    assert full["remaining_quantity"] == "0"

    monkeypatch.setattr(
        module.DailyInspectionService,
        "run_and_create_proposal",
        lambda **kwargs: {"mode": "proposal", **kwargs},
    )
    monkeypatch.setattr(
        module.DailyInspectionService,
        "run",
        lambda **kwargs: {"mode": "inspection", **kwargs},
    )
    assert (
        module.run_daily_inspection(
            account_id=3,
            inspection_date=date(2026, 7, 24),
            strategy_id=5,
            auto_create_proposal=True,
        )["mode"]
        == "proposal"
    )
    assert (
        module.run_daily_inspection(
            account_id=3,
            inspection_date=None,
            strategy_id=None,
            auto_create_proposal=False,
        )["mode"]
        == "inspection"
    )


def test_account_trade_payloads_filter_dates_and_stop_at_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-app trade reads enforce date bounds, JSON conversion, and output limits."""

    def _trade(trade_id: str, execution_date: date) -> SimpleNamespace:
        return SimpleNamespace(
            trade_id=trade_id,
            account_id=3,
            asset_code="000001.SZ",
            asset_name="asset",
            asset_type="stock",
            action=TradeAction.BUY,
            quantity=Decimal("2"),
            price=Decimal("10"),
            amount=Decimal("20"),
            commission=Decimal("0.1"),
            slippage=Decimal("0.01"),
            total_cost=Decimal("20.11"),
            fee_amounts_known=True,
            fee_amounts_status="known",
            current_commission=Decimal("0.1"),
            current_transfer_fee=Decimal("0.0"),
            current_stamp_duty=Decimal("0.0"),
            current_total_cost=Decimal("20.11"),
            current_realized_pnl=None,
            current_realized_pnl_pct=None,
            fee_correction_revision=None,
            fee_correction_overlay_applied=False,
            cost_basis_known=True,
            cost_basis_status="known",
            realized_pnl=None,
            realized_pnl_pct=None,
            reason="signal",
            signal_id="signal-1",
            order_date=execution_date,
            execution_date=execution_date,
            execution_time=datetime(
                execution_date.year,
                execution_date.month,
                execution_date.day,
                9,
                30,
                tzinfo=UTC,
            ),
            status=SimpleNamespace(value="executed"),
        )

    trades = [
        _trade("before", date(2026, 7, 1)),
        _trade("inside-1", date(2026, 7, 20)),
        _trade("inside-2", date(2026, 7, 21)),
        _trade("after", date(2026, 7, 25)),
    ]
    monkeypatch.setattr(
        module,
        "get_simulated_trade_repository",
        lambda: SimpleNamespace(get_by_account=lambda account_id: trades),
    )
    payloads = module.list_account_trade_payloads(
        account_id=3,
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 24),
        limit=1,
    )
    assert [payload["trade_id"] for payload in payloads] == ["inside-1"]
    assert payloads[0]["quantity"] == "2"
    assert payloads[0]["realized_pnl"] is None
    assert payloads[0]["fee_amounts_known"] is True
    assert payloads[0]["fee_amounts_status"] == "known"
    assert payloads[0]["cost_basis_known"] is True
    assert payloads[0]["cost_basis_status"] == "known"


def test_build_auto_engine_and_admin_dashboard_use_application_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine uses the guarded bridge while dashboard reads stay repository-backed."""
    account_repo = SimpleNamespace(
        count_active_account_models=lambda: 2,
        sum_active_total_value=lambda: Decimal("200"),
        get_active_accounts=lambda: [
            SimpleNamespace(
                account_id=3,
                cash_known=True,
                total_value=Decimal("200"),
            )
        ],
    )
    position_repo = SimpleNamespace(
        count_position_models=lambda: 3,
        get_by_account=lambda account_id: [],
    )
    trade_repo = SimpleNamespace(
        count_trade_models=lambda: 4,
        summarize_trade_models_for_date=lambda day: {
            "buy_count": 1,
            "sell_count": 2,
        },
        sum_realized_pnl_for_closed_trades=lambda: {
            "realized_pnl": Decimal("5"),
            "known": True,
            "covered_executed_sell_count": 2,
            "executed_sell_count": 2,
            "effective_realized_pnl": Decimal("5"),
            "effective_known": True,
            "effective_covered_executed_sell_count": 2,
        },
    )
    signal_repo = SimpleNamespace()
    monkeypatch.setattr(module, "get_simulated_account_repository", lambda: account_repo)
    monkeypatch.setattr(module, "get_simulated_position_repository", lambda: position_repo)
    monkeypatch.setattr(module, "get_simulated_trade_repository", lambda: trade_repo)
    monkeypatch.setattr(module, "get_signal_repository", lambda: signal_repo)
    daily_net_value_repo = SimpleNamespace()
    monkeypatch.setattr(
        module,
        "get_simulated_daily_net_value_repository",
        lambda: daily_net_value_repo,
    )
    performance_factory = Mock(return_value="performance")
    monkeypatch.setattr(module, "GetAccountPerformanceUseCase", performance_factory)
    bridge = SimpleNamespace(
        buy_use_case="settlement-buy",
        sell_use_case="settlement-sell",
        price_provider="qualified-price-provider",
    )
    invocation_id = UUID("b791989b-0d4e-4598-a4f8-277537c4a79a")
    bridge_calls: list[UUID] = []

    def bridge_for_invocation(run_id: UUID) -> SimpleNamespace:
        """Bind Engine order ports to the exact preparing invocation."""
        bridge_calls.append(run_id)
        return bridge

    monkeypatch.setattr(module, "get_automatic_trade_execution_bridge", bridge_for_invocation)
    asset_pool_factory = Mock(return_value="asset-pool")
    monkeypatch.setattr(module, "AssetPoolQueryService", asset_pool_factory)
    monkeypatch.setattr(module, "get_asset_pool_query_repository", lambda: "pool-repo")
    exit_advisor_factory = Mock(return_value="exit")
    link_recorder_factory = Mock(return_value="links")
    monkeypatch.setattr(module, "build_decision_rhythm_exit_advisor", exit_advisor_factory)
    monkeypatch.setattr(module, "build_decision_execution_link_recorder", link_recorder_factory)
    engine_factory = Mock(side_effect=lambda **kwargs: kwargs)
    monkeypatch.setattr(module, "AutoTradingEngine", engine_factory)

    engine = module.build_auto_trading_engine(invocation_id=invocation_id)
    assert bridge_calls == [invocation_id]
    assert engine["account_repo"] is account_repo
    assert engine["position_repo"] is position_repo
    assert engine["trade_repo"] is trade_repo
    assert engine["buy_use_case"] == "settlement-buy"
    assert engine["sell_use_case"] == "settlement-sell"
    assert engine["performance_use_case"] == "performance"
    assert engine["asset_pool_service"] == "asset-pool"
    assert engine["price_provider"] == "qualified-price-provider"
    assert engine["signal_service"] is signal_repo
    assert engine["exit_advisor"] == "exit"
    assert engine["execution_link_recorder"] == "links"
    performance_factory.assert_called_once_with(
        account_repo,
        position_repo,
        trade_repo,
        daily_net_value_repo,
    )
    asset_pool_factory.assert_called_once_with(
        asset_pool_repo="pool-repo",
        signal_repo=signal_repo,
    )
    exit_advisor_factory.assert_called_once_with()
    link_recorder_factory.assert_called_once_with()
    engine_factory.assert_called_once()
    dashboard = module.build_admin_dashboard_context()
    assert dashboard == {
        "total_accounts": 2,
        "total_positions": 3,
        "total_trades": 4,
        "today_buy_count": 1,
        "today_sell_count": 2,
        "total_capital": Decimal("200"),
        "total_pnl": Decimal("5"),
        "total_pnl_known": True,
        "effective_total_pnl": Decimal("5"),
        "effective_total_pnl_known": True,
        "total_pnl_covered_sell_count": 2,
        "total_pnl_executed_sell_count": 2,
    }
