"""Trade-list JSON and schema contract for original/effective fee-corrected PnL."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from rest_framework.fields import empty
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.simulated_trading.application import interface_services
from apps.simulated_trading.domain.entities import (
    AccountType,
    OrderStatus,
    SimulatedAccount,
    SimulatedTrade,
    TradeAction,
)
from apps.simulated_trading.interface import _portfolio_views
from apps.simulated_trading.interface._portfolio_views import TradeListAPIView
from apps.simulated_trading.interface.serializers import (
    TradeListResponseSerializer,
    TradeResponseSerializer,
)


class _AccountRepository:
    """Read-only account port for the view boundary test."""

    def __init__(self, account: SimulatedAccount) -> None:
        self.account = account

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        return self.account if account_id == self.account.account_id else None


class _TradeRepository:
    """Return fixed Domain trades without touching persistence."""

    def __init__(self, trades: list[SimulatedTrade]) -> None:
        self.trades = trades

    def get_by_account(self, account_id: int) -> list[SimulatedTrade]:
        return [trade for trade in self.trades if trade.account_id == account_id]


class _SchemaView:
    """Minimal versioning surface used to inspect the endpoint schema annotation."""

    request = object()
    kwargs: dict[str, object] = {}

    def determine_version(self, request: object, **kwargs: object) -> tuple[None, None]:
        del request, kwargs
        return None, None


def _account() -> SimulatedAccount:
    """Build the real immutable Domain account required by the view."""

    return SimulatedAccount(
        account_id=71,
        account_name="PnL schema contract",
        account_type=AccountType.SIMULATED,
        initial_capital=1000.0,
        current_cash=800.0,
        current_market_value=200.0,
        total_value=1000.0,
        start_date=date(2026, 10, 1),
    )


def _trade(
    trade_id: int,
    *,
    asset_code: str,
    action: TradeAction = TradeAction.SELL,
    fee_amounts_known: bool | None = True,
    cost_basis_known: bool | None = True,
    realized_pnl: float | None = 1.25,
    realized_pnl_pct: float | None = 1.25,
    commission: float = 0.10,
    transfer_fee: float | None = 0.03,
    stamp_duty: float | None = 0.04,
    total_cost: float = 100.10,
    effective_realized_pnl: float | None = None,
    effective_realized_pnl_pct: float | None = None,
    fee_correction_revision: int | None = None,
    fee_correction_overlay_applied: bool = False,
) -> SimulatedTrade:
    """Build an actual Domain trade with explicit original and overlay values."""

    return SimulatedTrade(
        trade_id=trade_id,
        account_id=71,
        asset_code=asset_code,
        asset_name=asset_code,
        asset_type="equity",
        action=action,
        quantity=10.0,
        price=10.0,
        amount=100.0,
        order_date=date(2026, 10, 2),
        execution_date=date(2026, 10, 2),
        execution_time=datetime(2026, 10, 2, 9, 30, tzinfo=UTC),
        commission=commission,
        slippage=0.0,
        total_cost=total_cost,
        fee_amounts_known=fee_amounts_known,
        cost_basis_known=cost_basis_known,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
        status=OrderStatus.EXECUTED,
        transfer_fee=transfer_fee,
        stamp_duty=stamp_duty,
        effective_commission=0.12 if fee_correction_revision is not None else None,
        effective_transfer_fee=0.05 if fee_correction_revision is not None else None,
        effective_stamp_duty=0.06 if fee_correction_revision is not None else None,
        effective_total_cost=100.23 if fee_correction_revision is not None else None,
        effective_realized_pnl=effective_realized_pnl,
        effective_realized_pnl_pct=effective_realized_pnl_pct,
        fee_correction_revision=fee_correction_revision,
        fee_correction_overlay_applied=fee_correction_overlay_applied,
    )


def _render_trade_list(
    monkeypatch: pytest.MonkeyPatch,
    account: SimulatedAccount,
    trades: list[SimulatedTrade],
    *,
    limit: int,
    asset_code: str | None = None,
) -> Response:
    """Render the real DRF view while replacing only its repository/auth boundaries."""

    account_repo = _AccountRepository(account)
    trade_repo = _TradeRepository(trades)
    monkeypatch.setattr(interface_services, "get_account_repository", lambda: account_repo)
    monkeypatch.setattr(interface_services, "get_trade_repository", lambda: trade_repo)
    monkeypatch.setattr(
        _portfolio_views,
        "_get_owned_account_or_response",
        lambda request, account_id, action: account,
    )

    query: dict[str, str] = {"limit": str(limit), "action": "sell"}
    if asset_code is not None:
        query["asset_code"] = asset_code
    request = APIRequestFactory().get("/api/simulated-trading/accounts/71/trades/", query)
    force_authenticate(request, user=SimpleNamespace(pk=1, is_authenticated=True))
    response = TradeListAPIView.as_view()(request, account_id=account.account_id)
    assert response.status_code == 200
    response.render()
    assert response["Content-Type"].startswith("application/json")
    return response


def test_trade_serializers_expose_optional_effective_fields_and_keep_close_writer_compatible() -> (
    None
):
    """The OpenAPI response serializer describes overlays without inventing defaults."""

    trade_fields = TradeResponseSerializer().fields
    expected_row_fields = {
        "effective_commission",
        "effective_transfer_fee",
        "effective_stamp_duty",
        "effective_total_cost",
        "original_realized_pnl",
        "effective_realized_pnl",
        "original_realized_pnl_pct",
        "effective_realized_pnl_pct",
        "effective_realized_pnl_known",
        "effective_realized_pnl_pct_known",
        "fee_correction_revision",
        "fee_correction_overlay_applied",
    }
    assert expected_row_fields <= set(trade_fields)
    assert trade_fields["effective_transfer_fee"].allow_null is True
    assert trade_fields["effective_stamp_duty"].allow_null is True
    assert trade_fields["effective_commission"].allow_null is True
    assert trade_fields["effective_total_cost"].allow_null is True
    assert trade_fields["effective_realized_pnl"].allow_null is True
    assert trade_fields["effective_realized_pnl_known"].allow_null is True
    assert trade_fields["effective_realized_pnl_pct_known"].allow_null is True

    optional_row_fields = expected_row_fields
    assert all(trade_fields[name].required is False for name in optional_row_fields)
    assert all(trade_fields[name].default is empty for name in optional_row_fields)

    list_fields = TradeListResponseSerializer().fields
    assert {
        "effective_total_realized_pnl",
        "effective_total_realized_pnl_known",
    } <= set(list_fields)
    assert list_fields["effective_total_realized_pnl"].allow_null is True
    assert list_fields["effective_total_realized_pnl"].required is False
    assert list_fields["effective_total_realized_pnl"].default is empty
    assert list_fields["effective_total_realized_pnl_known"].required is False
    assert list_fields["effective_total_realized_pnl_known"].default is empty

    schema_class = TradeListAPIView.get.kwargs["schema"]
    schema = schema_class()
    schema.view = _SchemaView()
    schema.method = "GET"
    assert schema.get_response_serializers() == {200: TradeListResponseSerializer}

    legacy_close_payload: dict[str, object] = {
        "trade_id": 2,
        "account_id": 71,
        "asset_code": "000002.SZ",
        "asset_name": "000002.SZ",
        "asset_type": "equity",
        "action": "sell",
        "quantity": 10,
        "price": "10.0000",
        "amount": "100.00",
        "commission": "0.1000",
        "slippage": "0.0000",
        "total_cost": "100.10",
        "fee_amounts_known": True,
        "fee_amounts_status": "known",
        "cost_basis_known": True,
        "cost_basis_status": "known",
        "realized_pnl_known": True,
        "realized_pnl_status": "known",
        "realized_pnl_pct_known": True,
        "realized_pnl": "2.00",
        "realized_pnl_pct": 2.0,
        "reason": "close",
        "signal_id": None,
        "order_date": date(2026, 10, 2),
        "execution_date": date(2026, 10, 2),
        "execution_time": datetime(2026, 10, 2, 9, 30, tzinfo=UTC),
        "status": "executed",
    }
    legacy_data = TradeResponseSerializer(instance=legacy_close_payload).data
    assert legacy_data["original_realized_pnl"] == "2.00"
    assert legacy_data["original_realized_pnl_pct"] == 2.0
    assert legacy_data["effective_realized_pnl"] is None
    assert legacy_data["effective_realized_pnl_known"] is None
    assert legacy_data["fee_correction_revision"] is None
    assert "fee_correction_overlay_applied" not in legacy_data
    assert legacy_data["effective_commission"] is None
    assert legacy_data["effective_total_cost"] is None


def test_trade_list_view_renders_effective_values_unknowns_and_full_filter_totals_before_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rendered response preserves source values and exposes exact totals and schema fields."""

    account = _account()
    corrected = _trade(
        1,
        asset_code="000001.SZ",
        realized_pnl=1.25,
        realized_pnl_pct=1.25,
        effective_realized_pnl=0.95,
        effective_realized_pnl_pct=0.95,
        fee_correction_revision=1,
        fee_correction_overlay_applied=True,
    )
    unknown = _trade(
        2,
        asset_code="000002.SZ",
        fee_amounts_known=False,
        realized_pnl=0.0,
        realized_pnl_pct=0.0,
    )
    buy = _trade(3, asset_code="000001.SZ", action=TradeAction.BUY, realized_pnl=None)
    known_zero = _trade(
        4,
        asset_code="000003.SZ",
        realized_pnl=0.0,
        realized_pnl_pct=0.0,
        effective_realized_pnl=0.0,
        effective_realized_pnl_pct=0.0,
        fee_correction_revision=1,
        fee_correction_overlay_applied=True,
    )
    zero_fees = _trade(
        5,
        asset_code="000004.SZ",
        realized_pnl=0.0,
        realized_pnl_pct=0.0,
        commission=0.0,
        transfer_fee=0.0,
        stamp_duty=0.0,
        total_cost=0.0,
    )
    original_values = tuple(
        (
            trade.commission,
            trade.total_cost,
            trade.realized_pnl,
            trade.realized_pnl_pct,
        )
        for trade in (corrected, unknown, buy, known_zero, zero_fees)
    )
    trades = [corrected, unknown, buy, known_zero, zero_fees]

    limited_response = _render_trade_list(monkeypatch, account, trades, limit=1)
    limited = json.loads(limited_response.content)
    assert limited["total_trades"] == 4
    assert limited["total_sell_count"] == 4
    assert len(limited["trades"]) == 1
    assert limited["total_realized_pnl"] is None
    assert limited["total_realized_pnl_known"] is False
    assert limited["effective_total_realized_pnl"] is None
    assert limited["effective_total_realized_pnl_known"] is False

    known_row = limited["trades"][0]
    assert known_row["realized_pnl"] == "1.25"
    assert known_row["original_realized_pnl"] == "1.25"
    assert known_row["effective_realized_pnl"] == "0.95"
    assert known_row["original_realized_pnl_pct"] == 1.25
    assert known_row["effective_realized_pnl_pct"] == 0.95
    assert known_row["realized_pnl_known"] is True
    assert known_row["effective_realized_pnl_known"] is True
    assert known_row["fee_correction_revision"] == 1
    assert known_row["fee_correction_overlay_applied"] is True

    complete_response = _render_trade_list(monkeypatch, account, trades, limit=2)
    complete = json.loads(complete_response.content)
    unknown_row = complete["trades"][1]
    assert unknown_row["realized_pnl"] is None
    assert unknown_row["original_realized_pnl"] == "0.0"
    assert unknown_row["effective_realized_pnl"] is None
    assert unknown_row["realized_pnl_known"] is False
    assert unknown_row["effective_realized_pnl_known"] is False
    assert unknown_row["realized_pnl_pct"] is None
    assert unknown_row["original_realized_pnl_pct"] == 0.0
    assert unknown_row["effective_realized_pnl_pct"] is None
    assert unknown_row["effective_realized_pnl_pct_known"] is False
    assert unknown_row["effective_commission"] is None
    assert unknown_row["effective_transfer_fee"] is None
    assert unknown_row["effective_stamp_duty"] is None
    assert unknown_row["effective_total_cost"] is None

    known_only_response = _render_trade_list(
        monkeypatch,
        account,
        trades,
        limit=1,
        asset_code="000001.SZ",
    )
    known_only = json.loads(known_only_response.content)
    assert known_only["total_realized_pnl"] == "1.25"
    assert known_only["total_realized_pnl_known"] is True
    assert known_only["effective_total_realized_pnl"] == "0.95"
    assert known_only["effective_total_realized_pnl_known"] is True

    known_zero_response = _render_trade_list(
        monkeypatch,
        account,
        trades,
        limit=1,
        asset_code="000003.SZ",
    )
    known_zero_payload = json.loads(known_zero_response.content)
    assert known_zero_payload["total_realized_pnl"] == "0.00"
    assert known_zero_payload["total_realized_pnl_known"] is True
    assert known_zero_payload["effective_total_realized_pnl"] == "0.00"
    assert known_zero_payload["effective_total_realized_pnl_known"] is True
    assert known_zero_payload["trades"][0]["realized_pnl"] == "0.0"
    assert known_zero_payload["trades"][0]["effective_realized_pnl"] == "0.0"
    assert known_zero_payload["trades"][0]["realized_pnl_known"] is True
    assert known_zero_payload["trades"][0]["effective_realized_pnl_known"] is True

    zero_fees_response = _render_trade_list(
        monkeypatch,
        account,
        trades,
        limit=1,
        asset_code="000004.SZ",
    )
    zero_fees_payload = json.loads(zero_fees_response.content)
    zero_fees_row = zero_fees_payload["trades"][0]
    assert zero_fees_row["fee_amounts_known"] is True
    assert zero_fees_row["effective_commission"] == "0.0"
    assert zero_fees_row["effective_transfer_fee"] == "0.0"
    assert zero_fees_row["effective_stamp_duty"] == "0.0"
    assert zero_fees_row["effective_total_cost"] == "0.0"

    assert (
        tuple(
            (
                trade.commission,
                trade.total_cost,
                trade.realized_pnl,
                trade.realized_pnl_pct,
            )
            for trade in trades
        )
        == original_values
    )
