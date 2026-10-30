"""ASH-01 settlement regressions through the current manual trade HTTP caller."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.test import APIClient

from apps.decision_rhythm.application.use_cases import ExecuteDecisionUseCase
from apps.decision_rhythm.domain.entities import ExecutionStatus
from apps.decision_rhythm.interface import workflow_api_views
from apps.risk_center.domain.execution_trading_constraints import SellOddLotMode
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.api.conftest import active_decision_runtime as active_decision_runtime
from tests.api.conftest import api_client as api_client
from tests.api.conftest import auth_user as auth_user
from tests.api.conftest import authenticated_client as authenticated_client
from tests.api.conftest import owned_account as owned_account
from tests.api.test_manual_trade_current_reference import (
    AS_OF,
    _body,
    _install_legacy_guards,
    _install_manual_service,
    _position,
    _post,
    _seed_fee,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _bundle_with_sell_step_100,
)

pytestmark = pytest.mark.django_db


def _seed_sellable_position(
    account: SimulatedAccountModel, *, quantity: int, available_quantity: int
) -> PositionModel:
    """Adapt the existing exact owner fixture to an ASH-01 share balance."""
    position = _position(account)
    account.refresh_from_db()
    value = Decimal(quantity) * Decimal("10.00")
    PositionModel._default_manager.using("default").filter(pk=position.pk).update(
        quantity=Decimal(quantity),
        available_quantity=Decimal(available_quantity),
        total_cost=value,
        market_value=value,
    )
    SimulatedAccountModel._default_manager.using("default").filter(pk=account.pk).update(
        current_market_value=value,
        total_value=account.current_cash + value,
    )
    position.refresh_from_db()
    account.refresh_from_db()
    return position


def test_new_a_share_buy_is_not_sellable_on_execution_day(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_fee(owned_account)
    _install_manual_service(monkeypatch, account=owned_account)
    legacy_calls = _install_legacy_guards(monkeypatch)

    response = _post(authenticated_client, account_id=owned_account.pk)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    position = PositionModel.objects.get(account=owned_account, asset_code="600000.SH")
    trade = SimulatedTradeModel.objects.get(account=owned_account)
    assert position.quantity == Decimal("100")
    assert position.available_quantity == Decimal("0")
    assert trade.settlement_status == "pending"
    assert trade.execution_date == AS_OF.date()
    assert legacy_calls == []


def test_a_share_addition_keeps_only_prior_day_shares_sellable(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_fee(owned_account)
    position = _seed_sellable_position(owned_account, quantity=300, available_quantity=300)
    _install_manual_service(monkeypatch, account=owned_account)
    legacy_calls = _install_legacy_guards(monkeypatch)

    response = _post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_body(quantity=200),
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    position.refresh_from_db()
    assert position.quantity == Decimal("500")
    assert position.available_quantity == Decimal("300")
    assert SimulatedTradeModel.objects.get(account=owned_account).settlement_status == "pending"
    assert legacy_calls == []


@pytest.mark.parametrize(
    ("sell_quantity", "expected_remaining"),
    [(150, 0), (50, 100)],
)
def test_a_share_qualified_odd_lot_sale(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
    sell_quantity: int,
    expected_remaining: int,
) -> None:
    _seed_fee(owned_account)
    _seed_sellable_position(owned_account, quantity=150, available_quantity=150)
    state = _install_manual_service(monkeypatch, account=owned_account)
    state.rule_reader.bundle = _bundle_with_sell_step_100(
        as_of=AS_OF, mode=SellOddLotMode.SELL_ODD_REMAINDER_ONCE
    )
    legacy_calls = _install_legacy_guards(monkeypatch)

    response = _post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_body(action="sell", quantity=sell_quantity),
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    trade = SimulatedTradeModel.objects.get(account=owned_account)
    assert trade.quantity == Decimal(sell_quantity)
    remaining = PositionModel.objects.filter(account=owned_account).first()
    if expected_remaining == 0:
        assert remaining is None
    else:
        assert remaining is not None
        assert remaining.quantity == Decimal(expected_remaining)
        assert remaining.available_quantity == Decimal(expected_remaining)
    assert legacy_calls == []


def test_a_share_odd_remainder_cannot_be_split_into_multiple_odd_lots(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_fee(owned_account)
    position = _seed_sellable_position(owned_account, quantity=150, available_quantity=150)
    state = _install_manual_service(monkeypatch, account=owned_account)
    state.rule_reader.bundle = _bundle_with_sell_step_100(
        as_of=AS_OF, mode=SellOddLotMode.SELL_ODD_REMAINDER_ONCE
    )
    legacy_calls = _install_legacy_guards(monkeypatch)
    cash_before = owned_account.current_cash

    response = _post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_body(action="sell", quantity=25),
    )

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    position.refresh_from_db()
    owned_account.refresh_from_db()
    assert position.quantity == Decimal("150")
    assert position.available_quantity == Decimal("150")
    assert owned_account.current_cash == cash_before
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 0
    assert legacy_calls == []


@pytest.mark.parametrize("action,quantity", [("buy", 100), ("sell", 50)])
def test_decision_simulated_consumer_uses_the_same_settlement_ledger(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    quantity: int,
) -> None:
    _seed_fee(owned_account)
    if action == "sell":
        _seed_sellable_position(owned_account, quantity=150, available_quantity=150)
    state = _install_manual_service(monkeypatch, account=owned_account)
    if action == "sell":
        state.rule_reader.bundle = _bundle_with_sell_step_100(
            as_of=AS_OF, mode=SellOddLotMode.SELL_ODD_REMAINDER_ONCE
        )
    request_repo = Mock()
    request_repo.get_by_id.return_value = SimpleNamespace(
        execution_status=ExecutionStatus.PENDING,
        candidate_id=None,
        asset_code="600000.SH",
    )
    use_case = ExecuteDecisionUseCase(
        request_repo=request_repo,
        candidate_repo=Mock(),
        manual_trade_use_case=state.build_service(),
    )
    dependencies = SimpleNamespace(request_repo=request_repo, use_case=use_case)
    monkeypatch.setattr(
        workflow_api_views,
        "build_execute_decision_dependencies",
        lambda: dependencies,
    )

    response = authenticated_client.post(
        f"/api/decision-rhythm/requests/ash01-decision-{action}/execute/",
        {
            "target": "SIMULATED",
            "sim_account_id": owned_account.pk,
            "asset_code": "600000.SH",
            "action": action,
            "quantity": quantity,
            "price": "10.0000",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["success"] is True
    position = PositionModel.objects.get(account=owned_account, asset_code="600000.SH")
    trade = SimulatedTradeModel.objects.get(account=owned_account)
    assert trade.quantity == Decimal(quantity)
    if action == "buy":
        assert position.quantity == Decimal("100")
        assert position.available_quantity == Decimal("0")
        assert trade.settlement_status == "pending"
    else:
        assert position.quantity == Decimal("100")
        assert position.available_quantity == Decimal("100")
    request_repo.update_execution_status.assert_called_once()
