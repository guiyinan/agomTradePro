"""Direct page and API contracts for simulated trading views."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.http import Http404
from rest_framework.exceptions import NotAuthenticated
from rest_framework.response import Response

from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingIssue,
    AutoTradingIssueKind,
)
from apps.simulated_trading.domain.entities import AccountCashReconciliationStatus
from apps.simulated_trading.interface import views as view_module
from apps.simulated_trading.interface.serializers import AutoTradingRunResponseSerializer
from apps.simulated_trading.interface.views import (
    AutoTradingAPIView,
    DailyInspectionReportListAPIView,
    DailyInspectionRunAPIView,
    EquityCurveAPIView,
    ManualTradeAPIView,
    _account_payload,
    _authenticated_user_id,
    _get_owned_account_or_response,
    _parse_iso_date,
    _parse_positive_int,
)
from core.exceptions import DataFetchError
from tests.unit.simulated_trading.test_automatic_invocation_application import (
    _MemoryInvocationRepository,
)


def _raw(function: object) -> object:
    return inspect.unwrap(function)


def _request(
    *,
    method: str = "GET",
    data: dict[str, object] | None = None,
    query: dict[str, object] | None = None,
    idempotency_key: str = "t5-auto-run-001",
) -> SimpleNamespace:
    return SimpleNamespace(
        method=method,
        POST=data or {},
        data=data or {},
        query_params=query or {},
        headers={"Idempotency-Key": idempotency_key},
        user=SimpleNamespace(id=7, pk=7, is_authenticated=True, is_superuser=False),
    )


@pytest.fixture(autouse=True)
def _use_typed_memory_invocation_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise each real invocation Application call without database storage."""
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "get_auto_invocation_repository",
        lambda: _MemoryInvocationRepository(),
    )


def _account() -> SimpleNamespace:
    return SimpleNamespace(
        account_id=1,
        account_name="模拟账户",
        account_type=SimpleNamespace(value="simulated"),
        cash_known=True,
        cash_reconciliation_status=AccountCashReconciliationStatus.SIMULATED_LEDGER,
        initial_capital=Decimal("100000"),
        current_cash=Decimal("50000"),
        current_market_value=Decimal("50000"),
        total_value=Decimal("100000"),
        total_return=0.1,
        annual_return=0.2,
        max_drawdown=-0.05,
        sharpe_ratio=1.2,
        win_rate=0.6,
        max_position_pct=0.2,
        stop_loss_pct=0.1,
        commission_rate=0.0003,
        slippage_rate=0.001,
        total_trades=10,
        winning_trades=6,
        is_active=True,
        auto_trading_enabled=False,
        start_date=date(2026, 1, 1),
        last_trade_date=date(2026, 7, 1),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class FakeSerializer:
    def __init__(self, *, data: dict[str, object]) -> None:
        self.validated_data = data

    def is_valid(self, *, raise_exception: bool) -> bool:
        return raise_exception


def test_shared_view_helpers_validate_access_dates_counts_and_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allowed = SimpleNamespace(allowed=True, account=SimpleNamespace(id=1))
    denied = SimpleNamespace(allowed=False, error="forbidden", status_code=403)
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "get_account_access",
        lambda **_kwargs: allowed,
    )
    assert _get_owned_account_or_response(_request(), 1).id == 1
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "get_account_access",
        lambda **_kwargs: denied,
    )
    assert isinstance(_get_owned_account_or_response(_request(), 1), Response)

    assert _parse_iso_date("2026-07-01", field_name="start") == date(2026, 7, 1)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _parse_iso_date("bad", field_name="start")
    assert _parse_positive_int(None, field_name="limit", default=20) == 20
    assert _parse_positive_int("2", field_name="limit", default=20) == 2
    with pytest.raises(ValueError, match="必须是整数"):
        _parse_positive_int("bad", field_name="limit", default=20)
    with pytest.raises(ValueError, match="大于 0"):
        _parse_positive_int(0, field_name="limit", default=20)
    assert _authenticated_user_id(_request()) == 7
    with pytest.raises(NotAuthenticated):
        _authenticated_user_id(SimpleNamespace(user=SimpleNamespace(id=None)))


def test_account_payload_masks_derived_fields_for_new_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "has_current_position_valuation",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "has_complete_closed_trade_costs",
        MagicMock(return_value=True),
    )
    normal = _account_payload(_account())
    assert normal["cash_known"] is True
    assert normal["cash_reconciliation_status"] == "simulated_ledger"
    assert normal["current_cash"] == "50000"
    assert normal["total_return"] == 0.1
    assert normal["last_trade_date"] == "2026-07-01"
    assert normal["created_at"].startswith("2026-01-01")

    created = _account_payload(_account(), newly_created=True)
    assert created["cash_known"] is True
    assert created["cash_reconciliation_status"] == "simulated_ledger"
    assert created["current_cash"] == "50000"
    assert created["total_return"] is None
    assert created["last_trade_date"] is None
    assert created["created_at"] is None


def test_my_accounts_page_validation_create_and_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        view_module,
        "redirect",
        lambda path: SimpleNamespace(status_code=302, url=path),
    )
    monkeypatch.setattr(
        view_module,
        "render",
        lambda request, template, context=None: SimpleNamespace(
            status_code=200,
            template=template,
            context=context,
        ),
    )
    from django.contrib import messages

    monkeypatch.setattr(messages, "error", MagicMock())
    monkeypatch.setattr(messages, "success", MagicMock())
    function = _raw(view_module.my_accounts_page)

    assert function(_request(method="POST", data={"initial_capital": "bad"})).status_code == 302
    assert (
        function(
            _request(
                method="POST",
                data={"account_type": "bad", "account_name": "x", "initial_capital": "1"},
            )
        ).status_code
        == 302
    )
    assert (
        function(
            _request(
                method="POST",
                data={"account_type": "simulated", "account_name": "", "initial_capital": "1"},
            )
        ).status_code
        == 302
    )
    assert (
        function(
            _request(
                method="POST",
                data={"account_type": "simulated", "account_name": "x", "initial_capital": "0"},
            )
        ).status_code
        == 302
    )

    create = MagicMock()
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "create_account_for_user",
        create,
    )
    valid = _request(
        method="POST",
        data={
            "account_type": "real",
            "account_name": "real account",
            "initial_capital": "100",
        },
    )
    assert function(valid).status_code == 302
    create.assert_called_once()

    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "build_my_accounts_context",
        lambda _user: {"accounts": []},
    )
    assert function(_request()).context == {"accounts": []}


@pytest.mark.parametrize(
    ("function_name", "service_name"),
    [
        ("my_account_detail_page", "build_my_account_detail_context"),
        ("my_positions_page", "build_my_positions_context"),
        ("my_trades_page", "build_my_trades_context"),
    ],
)
def test_owned_pages_render_or_raise_not_found(
    monkeypatch: pytest.MonkeyPatch,
    function_name: str,
    service_name: str,
) -> None:
    monkeypatch.setattr(
        view_module,
        "render",
        lambda request, template, context: SimpleNamespace(status_code=200, context=context),
    )
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        service_name,
        lambda _user, _id: {"account": 1},
    )
    function = _raw(getattr(view_module, function_name))
    assert function(_request(), 1).status_code == 200
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        service_name,
        lambda _user, _id: None,
    )
    with pytest.raises(Http404):
        function(_request(), 1)


def test_inspection_notification_page_handles_missing_invalid_and_valid_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The notification page validates recipients before persisting settings."""

    from django.contrib import messages

    monkeypatch.setattr(messages, "error", MagicMock())
    monkeypatch.setattr(messages, "success", MagicMock())
    monkeypatch.setattr(
        view_module,
        "render",
        lambda request, template, context: SimpleNamespace(
            status_code=200,
            template=template,
            context=context,
        ),
    )
    monkeypatch.setattr(
        view_module,
        "redirect",
        lambda path: SimpleNamespace(status_code=302, url=path),
    )
    function = _raw(view_module.my_inspection_notify_page)
    context_builder = MagicMock(return_value=None)
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "build_inspection_notify_context",
        context_builder,
    )
    with pytest.raises(Http404):
        function(_request(), 1)

    context_builder.return_value = {"config": None}
    invalid = function(
        _request(
            method="POST",
            data={
                "is_enabled": "on",
                "include_owner_email": "on",
                "notify_on": "unsupported",
                "recipient_emails": "valid@example.com; broken\n",
            },
        ),
        1,
    )
    assert invalid.status_code == 200
    messages.error.assert_called_once()

    save = MagicMock()
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "save_inspection_notification_config",
        save,
    )
    valid = function(
        _request(
            method="POST",
            data={
                "is_enabled": "on",
                "include_owner_email": "on",
                "notify_on": "all",
                "recipient_emails": "first@example.com,\nsecond@example.com",
            },
        ),
        1,
    )
    assert valid.status_code == 302
    save.assert_called_once_with(
        account_id=1,
        is_enabled=True,
        include_owner_email=True,
        notify_on="all",
        recipient_emails=["first@example.com", "second@example.com"],
    )
    messages.success.assert_called_once()


def _trade() -> SimpleNamespace:
    return SimpleNamespace(
        trade_id=1,
        account_id=1,
        asset_code="600000.SH",
        asset_name="浦发银行",
        asset_type="equity",
        action=SimpleNamespace(value="buy"),
        quantity=100,
        price=Decimal("10"),
        amount=Decimal("1000"),
        commission=Decimal("1"),
        slippage=Decimal("0"),
        total_cost=Decimal("1001"),
        fee_amounts_known=True,
        fee_amounts_status="known",
        cost_basis_known=True,
        cost_basis_status="known",
        realized_pnl=None,
        realized_pnl_pct=None,
        reason="test",
        signal_id=None,
        order_date=date(2026, 7, 1),
        execution_date=date(2026, 7, 1),
        execution_time=datetime(2026, 7, 1, tzinfo=UTC),
        status=SimpleNamespace(value="executed"),
    )


@pytest.mark.parametrize("action", ["buy", "sell"])
def test_manual_trade_buy_sell_and_business_error(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    monkeypatch.setattr(
        view_module,
        "_get_owned_account_or_response",
        lambda *_args, **_kwargs: SimpleNamespace(id=1),
    )
    calls: list[object] = []
    should_fail = False

    class _ManualCaller:
        def execute(self, request: object) -> object:
            calls.append(request)
            if should_fail:
                raise ValueError("insufficient cash")
            trade = _trade()
            trade.action = SimpleNamespace(value=action)
            return SimpleNamespace(
                trade=trade,
                receipt=SimpleNamespace(replayed=False),
            )

    monkeypatch.setattr(
        view_module,
        "build_current_reference_manual_trade_use_case",
        lambda: _ManualCaller(),
        raising=False,
    )
    legacy_calls: list[str] = []

    def legacy_factory(*_args: object, **_kwargs: object) -> object:
        def execute(**_params: object) -> None:
            legacy_calls.append("legacy")
            raise ValueError("legacy caller must not run")

        return SimpleNamespace(execute=execute)

    monkeypatch.setattr(view_module, "ExecuteBuyOrderUseCase", legacy_factory)
    monkeypatch.setattr(view_module, "ExecuteSellOrderUseCase", legacy_factory)
    view = ManualTradeAPIView.__new__(ManualTradeAPIView)
    view.account_repo = MagicMock()
    view.position_repo = MagicMock()
    view.trade_repo = MagicMock()
    payload = {
        "action": action,
        "asset_code": "600000.SH",
        "asset_name": "浦发银行",
        "asset_type": "equity",
        "quantity": 100,
        "price": Decimal("10"),
    }
    request = _request(data=payload)
    request.headers = {"Idempotency-Key": "unit-current-reference-key"}
    response = view.post(request, 1)
    assert response.status_code == 200
    assert response.data["trade"]["trade_id"] == 1
    assert response.data["replayed"] is False
    trade_payload = response.data["trade"]
    assert trade_payload["fee_amounts_known"] is True
    assert trade_payload["fee_amounts_status"] == "known"
    assert trade_payload["cost_basis_known"] is True
    assert trade_payload["cost_basis_status"] == "known"
    if action == "buy":
        assert trade_payload["realized_pnl_known"] is None
        assert trade_payload["realized_pnl_status"] == "not_applicable"
        assert trade_payload["realized_pnl_pct_known"] is None
        assert trade_payload["realized_pnl"] is None
        assert trade_payload["realized_pnl_pct"] is None
    else:
        assert trade_payload["realized_pnl_known"] is False
        assert trade_payload["realized_pnl_status"] == "unknown"
        assert trade_payload["realized_pnl_pct_known"] is False
        assert trade_payload["realized_pnl"] is None
        assert trade_payload["realized_pnl_pct"] is None
    assert len(calls) == 1
    assert calls[0].account_id == 1
    assert calls[0].user_id == request.user.id
    assert calls[0].idempotency_key == "unit-current-reference-key"
    assert calls[0].asset_code == "600000.SH"
    assert calls[0].asset_type == "equity"
    assert calls[0].side.value == action
    assert calls[0].quantity == Decimal("100")
    assert type(calls[0].quantity) is Decimal
    assert calls[0].price == Decimal("10")
    assert type(calls[0].price) is Decimal
    assert calls[0].reason == ""
    assert calls[0].signal_id is None
    assert legacy_calls == []

    should_fail = True
    if action == "buy":
        error_response = view.post(request, 1)
        assert error_response.status_code == 400
        assert error_response.data["success"] is False
        assert error_response.data["code"]
    assert legacy_calls == []


def test_equity_curve_validation_success_and_data_fetch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        view_module,
        "_get_owned_account_or_response",
        lambda *_args, **_kwargs: SimpleNamespace(id=1),
    )
    view = EquityCurveAPIView.__new__(EquityCurveAPIView)
    view.account_repo = SimpleNamespace(get_by_id=lambda _id: _account())
    view.performance_calculator = SimpleNamespace(
        get_equity_curve=lambda **_kwargs: [{"date": "2026-07-01"}]
    )
    assert view.get(_request(query={"start_date": "bad"}), 1).status_code == 400
    assert (
        view.get(
            _request(query={"start_date": "2026-07-02", "end_date": "2026-07-01"}),
            1,
        ).status_code
        == 400
    )
    success = view.get(
        _request(query={"start_date": "2026-07-01", "end_date": "2026-07-02"}),
        1,
    )
    assert success.data["data_points"] == [{"date": "2026-07-01"}]

    view.performance_calculator = SimpleNamespace(
        get_equity_curve=lambda **_kwargs: (_ for _ in ()).throw(
            DataFetchError("feed down", code="FEED", details={"source": "x"})
        )
    )
    assert view.get(_request(), 1).status_code == 503
    view.account_repo = SimpleNamespace(get_by_id=lambda _id: None)
    assert view.get(_request(), 1).status_code == 404


def test_auto_trading_success_and_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(view_module, "AutoTradingRunRequestSerializer", FakeSerializer)
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "resolve_auto_trading_account_scope",
        lambda *_args: SimpleNamespace(
            allowed=True,
            account_ids=(1, 2),
            error=None,
            status_code=None,
        ),
    )
    engine = MagicMock()
    engine.run_daily_trading.return_value = {
        1: AccountAutoTradingOutcome(account_id=1, buy_count=2, sell_count=1),
        2: AccountAutoTradingOutcome(
            account_id=2,
            buy_count=0,
            sell_count=0,
            issues=(
                AutoTradingIssue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="risk_check",
                    code="ACCOUNT_BLOCKED",
                ),
            ),
        ),
    }
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "build_auto_trading_engine",
        lambda *, invocation_id, expected_owner_id=None: engine,
    )
    response = AutoTradingAPIView().post(
        _request(data={"trade_date": date(2026, 7, 1)}, idempotency_key="t5-auto-success-001")
    )
    assert response.status_code == 200
    assert response.data["outcome"] == "partial"
    assert response.data["success"] is True
    assert response.data["requested"] == 2
    assert response.data["failed"] == 1
    assert response.data["stored"] == 3
    assert response.data["summary"] == {
        "total_buy_count": 2,
        "total_sell_count": 1,
        "confirmed_trade_count": 3,
        "stored_trade_count": 3,
        "counts_unavailable": False,
    }
    response_contract = AutoTradingRunResponseSerializer(data=response.data)
    assert response_contract.is_valid(), response_contract.errors
    assert response.data["count_unit"] == "account"
    assert response.data["stored_count_unit"] == "trade"
    assert response.data["stable_error_code"] == "ACCOUNT_BLOCKED"
    engine.run_daily_trading.assert_called_once_with(date(2026, 7, 1), account_ids=[1, 2])

    engine.run_daily_trading.side_effect = RuntimeError("engine down")
    indeterminate = AutoTradingAPIView().post(
        _request(data={}, idempotency_key="t5-auto-unknown-001")
    )
    assert indeterminate.status_code == 200
    assert indeterminate.data["outcome"] == "failed"
    assert indeterminate.data["stored"] is None
    assert indeterminate.data["counts_unavailable"] is True


def test_auto_trading_missing_requested_result_is_unknown_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(view_module, "AutoTradingRunRequestSerializer", FakeSerializer)
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "resolve_auto_trading_account_scope",
        lambda *_args: SimpleNamespace(
            allowed=True,
            account_ids=(1, 2),
            error=None,
            status_code=None,
        ),
    )
    engine = MagicMock()
    engine.run_daily_trading.return_value = {
        1: AccountAutoTradingOutcome(account_id=1, buy_count=2, sell_count=0),
    }
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "build_auto_trading_engine",
        lambda *, invocation_id, expected_owner_id=None: engine,
    )

    response = AutoTradingAPIView().post(_request(data={}))

    assert response.status_code == 200
    assert response.data["outcome"] == "partial"
    assert response.data["requested"] == 2
    assert response.data["failed"] == 1
    assert response.data["buy_count"] == 2
    assert response.data["stored"] is None
    assert response.data["stable_error_code"] == "ACCOUNT_RESULT_MISSING"
    assert response.data["results"][2]["issues"][0]["code"] == "ACCOUNT_RESULT_MISSING"


def test_auto_trading_extra_result_marks_confirmed_storage_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(view_module, "AutoTradingRunRequestSerializer", FakeSerializer)
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "resolve_auto_trading_account_scope",
        lambda *_args: SimpleNamespace(
            allowed=True,
            account_ids=(1,),
            error=None,
            status_code=None,
        ),
    )
    engine = MagicMock()
    engine.run_daily_trading.return_value = {
        1: AccountAutoTradingOutcome(account_id=1, buy_count=2, sell_count=0),
        99: AccountAutoTradingOutcome(account_id=99, buy_count=1, sell_count=0),
    }
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "build_auto_trading_engine",
        lambda *, invocation_id, expected_owner_id=None: engine,
    )

    response = AutoTradingAPIView().post(_request(data={}))

    assert response.status_code == 200
    assert response.data["buy_count"] == 2
    assert response.data["stored"] is None
    assert response.data["counts_unavailable"] is True
    assert response.data["stable_error_code"] == "TASK_RESULT_CONTRACT_INVALID"
    assert response.data["results"][1]["issues"][-1]["effects_indeterminate"] is True


def test_auto_trading_engine_setup_failure_stays_an_operational_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(view_module, "AutoTradingRunRequestSerializer", FakeSerializer)
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "resolve_auto_trading_account_scope",
        lambda *_args: SimpleNamespace(
            allowed=True,
            account_ids=(1,),
            error=None,
            status_code=None,
        ),
    )
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "build_auto_trading_engine",
        MagicMock(side_effect=RuntimeError("private configuration detail")),
    )

    response = AutoTradingAPIView().post(_request(data={}))

    assert response.status_code == 500
    assert response.data == {
        "success": False,
        "error": "自动交易引擎初始化失败",
        "stable_error_code": "AUTO_TRADING_SETUP_FAILED",
    }


def test_auto_trading_rejects_unowned_account_before_building_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly selected foreign account must never reach engine construction."""
    monkeypatch.setattr(view_module, "AutoTradingRunRequestSerializer", FakeSerializer)
    access_checks: list[tuple[object, int, str]] = []

    def deny_access(user: object, account_id: int, action: str = "访问") -> SimpleNamespace:
        access_checks.append((user, account_id, action))
        return SimpleNamespace(
            allowed=False,
            account=None,
            error="无权执行自动交易该账户",
            status_code=403,
        )

    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "get_account_access",
        deny_access,
    )
    build_engine = MagicMock()
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "build_auto_trading_engine",
        build_engine,
    )

    response = AutoTradingAPIView().post(_request(data={"account_ids": [88]}))

    assert response.status_code == 403
    assert access_checks and access_checks[0][1] == 88
    build_engine.assert_not_called()


def test_auto_trading_rejects_real_account_before_building_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real accounts stay outside the simulated execution endpoint even for an owner."""
    monkeypatch.setattr(view_module, "AutoTradingRunRequestSerializer", FakeSerializer)
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "get_account_access",
        lambda *_args, **_kwargs: SimpleNamespace(
            allowed=True,
            account=SimpleNamespace(
                id=88,
                user_id=7,
                account_type="real",
                is_active=True,
                auto_trading_enabled=True,
            ),
            error=None,
            status_code=None,
        ),
    )
    build_engine = MagicMock()
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "build_auto_trading_engine",
        build_engine,
    )

    response = AutoTradingAPIView().post(_request(data={"account_ids": [88]}))

    assert response.status_code == 400
    build_engine.assert_not_called()


@pytest.mark.parametrize("account_ids", [[], None])
def test_auto_trading_empty_resolved_scope_returns_zero_summary_without_engine(
    monkeypatch: pytest.MonkeyPatch,
    account_ids: list[int] | None,
) -> None:
    """An empty scope is a no-op and must not initialize trading dependencies."""
    monkeypatch.setattr(view_module, "AutoTradingRunRequestSerializer", FakeSerializer)
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "resolve_auto_trading_account_scope",
        lambda *_args: SimpleNamespace(
            allowed=True,
            account_ids=(),
            error=None,
            status_code=None,
        ),
    )
    build_engine = MagicMock()
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "build_auto_trading_engine",
        build_engine,
    )

    response = AutoTradingAPIView().post(
        _request(data={"account_ids": account_ids} if account_ids is not None else {})
    )

    assert response.status_code == 200
    assert response.data["outcome"] == "noop"
    assert response.data["requested"] == 0
    assert response.data["stored"] == 0
    assert response.data["total_accounts"] == 0
    assert response.data["results"] == {}
    assert response.data["summary"] == {
        "total_buy_count": 0,
        "total_sell_count": 0,
        "confirmed_trade_count": 0,
        "stored_trade_count": 0,
        "counts_unavailable": False,
    }
    build_engine.assert_not_called()


def test_daily_inspection_run_and_history_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        view_module,
        "_get_owned_account_or_response",
        lambda *_args, **_kwargs: SimpleNamespace(id=1),
    )
    monkeypatch.setattr(view_module, "DailyInspectionRunRequestSerializer", FakeSerializer)
    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "run_daily_inspection",
        lambda **_kwargs: {"report_id": 1},
    )
    run_view = DailyInspectionRunAPIView()
    assert run_view.post(_request(data={}), 1).data["count"] == 1

    for error, status_code in (
        (ValueError("missing"), 404),
        (DataFetchError("down"), 500),
    ):
        monkeypatch.setattr(
            view_module.simulated_interface_services,
            "run_daily_inspection",
            lambda _error=error, **_kwargs: (_ for _ in ()).throw(_error),
        )
        response = run_view.post(_request(data={}), 1)
        assert response.status_code == status_code
        assert response.data == {"success": False, "error": str(error)}

    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "run_daily_inspection",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )
    with pytest.raises(RuntimeError, match="unexpected"):
        run_view.post(_request(data={}), 1)

    monkeypatch.setattr(
        view_module.simulated_interface_services,
        "list_daily_inspection_report_payloads",
        lambda **_kwargs: [{"report_id": 1}],
    )
    history = DailyInspectionReportListAPIView()
    assert (
        history.get(
            _request(query={"limit": 5, "inspection_date": "2026-07-01"}),
            1,
        ).data["count"]
        == 1
    )
    assert history.get(_request(query={"limit": 0}), 1).status_code == 400
