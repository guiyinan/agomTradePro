"""Read-surface regressions for incomplete historical sell facts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth.models import AbstractBaseUser
from django.test import Client
from rest_framework.test import APIClient

from apps.simulated_trading.application.use_cases import GetAccountPerformanceUseCase
from apps.simulated_trading.infrastructure.account_repository import (
    DjangoSimulatedAccountRepository,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from apps.simulated_trading.infrastructure.position_repository import DjangoPositionRepository
from apps.simulated_trading.infrastructure.trade_repository import DjangoTradeRepository

_EXECUTION_DATE = date(2026, 10, 16)


def _create_sell(
    account_id: int,
    *,
    asset_code: str,
    realized_pnl: Decimal,
    realized_pnl_pct: float,
    cost_basis_known: bool | None,
    fee_amounts_known: bool | None,
) -> SimulatedTradeModel:
    """Persist one closed sell while keeping its numeric legacy result intact."""

    return SimulatedTradeModel.objects.create(
        account_id=account_id,
        asset_code=asset_code,
        asset_name="Read surface cost fixture",
        asset_type="equity",
        action="sell",
        quantity=Decimal("100.000000"),
        price=Decimal("20.0000"),
        amount=Decimal("2000.00"),
        commission=Decimal("2.00"),
        transfer_fee=Decimal("0.03"),
        stamp_duty=Decimal("2.00"),
        slippage=Decimal("1.00"),
        total_cost=Decimal("2005.03"),
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
        cost_basis_known=cost_basis_known,
        fee_amounts_known=fee_amounts_known,
        order_date=_EXECUTION_DATE,
        execution_date=_EXECUTION_DATE,
        status="executed",
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("cost_basis_known", "fee_amounts_known"),
    (
        pytest.param(None, True, id="unknown-basis"),
        pytest.param(False, True, id="partial-basis"),
        pytest.param(True, None, id="unknown-fees"),
        pytest.param(True, False, id="partial-fees"),
    ),
)
def test_trade_list_api_and_classic_page_hide_incomplete_sell_returns(
    authenticated_client: APIClient,
    client: Client,
    auth_user: AbstractBaseUser,
    owned_account: object,
    cost_basis_known: bool | None,
    fee_amounts_known: bool | None,
) -> None:
    """API and Classic output must not present raw PnL or percent as complete."""

    account_id = int(owned_account.id)
    _create_sell(
        account_id,
        asset_code=f"KN{uuid4().hex[:8]}",
        realized_pnl=Decimal("987.65"),
        realized_pnl_pct=88.88,
        cost_basis_known=cost_basis_known,
        fee_amounts_known=fee_amounts_known,
    )

    api_response = authenticated_client.get(f"/api/simulated-trading/accounts/{account_id}/trades/")
    assert api_response.status_code == 200
    payload = api_response.json()
    assert payload["total_realized_pnl_known"] is False
    assert payload["total_realized_pnl"] is None
    assert len(payload["trades"]) == 1
    row = payload["trades"][0]
    assert row["realized_pnl"] is None
    assert row["realized_pnl_pct"] is None
    assert row["cost_basis_known"] is cost_basis_known
    assert row["fee_amounts_known"] is fee_amounts_known

    client.force_login(auth_user)
    classic_response = client.get(f"/simulated-trading/my-accounts/{account_id}/trades/")
    assert classic_response.status_code == 200
    assert classic_response.context["total_realized_pnl_known"] is False
    assert classic_response.context["total_realized_pnl"] is None
    assert b"987.65" not in classic_response.content
    assert b"88.88%" not in classic_response.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("cost_basis_known", "fee_amounts_known"),
    (
        pytest.param(None, True, id="unknown-basis"),
        pytest.param(False, True, id="partial-basis"),
        pytest.param(True, None, id="unknown-fees"),
        pytest.param(True, False, id="partial-fees"),
    ),
)
def test_account_win_rate_excludes_incomplete_numeric_sell_results(
    authenticated_client: APIClient,
    owned_account: object,
    cost_basis_known: bool | None,
    fee_amounts_known: bool | None,
) -> None:
    """A positive stored PnL with incomplete basis or fees is not a counted win."""

    account_id = int(owned_account.id)
    suffix = uuid4().hex[:8]
    _create_sell(
        account_id,
        asset_code=f"KP{suffix}",
        realized_pnl=Decimal("100.00"),
        realized_pnl_pct=10.0,
        cost_basis_known=cost_basis_known,
        fee_amounts_known=fee_amounts_known,
    )
    _create_sell(
        account_id,
        asset_code=f"KC{suffix}",
        realized_pnl=Decimal("-50.00"),
        realized_pnl_pct=-5.0,
        cost_basis_known=True,
        fee_amounts_known=True,
    )

    result = GetAccountPerformanceUseCase(
        DjangoSimulatedAccountRepository(),
        DjangoPositionRepository(),
        DjangoTradeRepository(),
    ).execute(account_id)

    assert result["total_trades"] == 2
    assert result["winning_trades"] is None
    assert result["win_rate"] is None
    assert result["win_rate_known"] is False

    response = authenticated_client.get(
        f"/api/simulated-trading/accounts/{account_id}/performance/"
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["win_rate_known"] is False
    for field in ("total_return", "annual_return", "max_drawdown", "sharpe_ratio"):
        assert payload["account"][field] is None
        assert payload["performance"][field] is None


@pytest.mark.django_db
def test_account_win_rate_keeps_complete_sell_results(
    owned_account: object,
) -> None:
    """Fully known positive and negative sells retain the established 50% rate."""

    account_id = int(owned_account.id)
    suffix = uuid4().hex[:8]
    complete_sells = (
        (f"KW{suffix}", Decimal("100.00")),
        (f"KL{suffix}", Decimal("-50.00")),
    )
    for asset_code, pnl in complete_sells:
        _create_sell(
            account_id,
            asset_code=asset_code,
            realized_pnl=pnl,
            realized_pnl_pct=10.0 if pnl > 0 else -5.0,
            cost_basis_known=True,
            fee_amounts_known=True,
        )

    result = GetAccountPerformanceUseCase(
        DjangoSimulatedAccountRepository(),
        DjangoPositionRepository(),
        DjangoTradeRepository(),
    ).execute(account_id)

    assert result["total_trades"] == 2
    assert result["winning_trades"] == 1
    assert result["win_rate"] == 50.0


@pytest.mark.django_db
def test_trade_list_keeps_numeric_returns_when_basis_and_fees_are_complete(
    authenticated_client: APIClient,
    client: Client,
    auth_user: AbstractBaseUser,
    owned_account: object,
) -> None:
    """Known basis and complete fees retain their existing numeric displays."""

    account_id = int(owned_account.id)
    _create_sell(
        account_id,
        asset_code=f"KC{uuid4().hex[:8]}",
        realized_pnl=Decimal("987.65"),
        realized_pnl_pct=88.88,
        cost_basis_known=True,
        fee_amounts_known=True,
    )

    api_response = authenticated_client.get(f"/api/simulated-trading/accounts/{account_id}/trades/")
    assert api_response.status_code == 200
    payload = api_response.json()
    assert payload["total_realized_pnl_known"] is True
    assert Decimal(payload["total_realized_pnl"]) == Decimal("987.65")
    row = payload["trades"][0]
    assert Decimal(row["realized_pnl"]) == Decimal("987.65")
    assert row["realized_pnl_pct"] == 88.88

    client.force_login(auth_user)
    classic_response = client.get(f"/simulated-trading/my-accounts/{account_id}/trades/")
    assert classic_response.status_code == 200
    assert classic_response.context["total_realized_pnl_known"] is True
    assert b"987.65" in classic_response.content
    assert b"88.88%" in classic_response.content
