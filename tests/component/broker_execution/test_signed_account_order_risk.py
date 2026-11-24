"""Order-level checks on the signed QMT values, independent of account certification."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.benchmark_day_source_composition import (
    SignedBrokerBalances,
    SignedPosition,
)
from apps.broker_execution.domain.connection_freshness import HEARTBEAT_FRESHNESS
from apps.broker_execution.domain.execution_contract_capabilities import (
    EXECUTION_CONSTRAINT_SCHEMA_V2,
)
from apps.broker_execution.infrastructure.models import BrokerAccountBindingModel, BrokerAgentModel
from apps.broker_execution.infrastructure.order_risk_reservations import OrderReservations
from apps.broker_execution.signed_account_risk_composition import (
    _heartbeat_deadline,
    _order_symbol_value,
)


def test_agent_deadline_uses_original_source_clock_not_fresh_receive_time():
    now = timezone.now()
    observed = now - HEARTBEAT_FRESHNESS + timedelta(seconds=2)
    agent = BrokerAgentModel(
        is_active=True,
        status=BrokerAgentModel.STATUS_ONLINE,
        qmt_connected=True,
        last_heartbeat_at=now,
        health_snapshot={
            "source_observed_at": observed.isoformat(),
            "execution_constraint_schemas": [EXECUTION_CONSTRAINT_SCHEMA_V2],
        },
    )
    assert _heartbeat_deadline(agent, now) == observed + HEARTBEAT_FRESHNESS
    with pytest.raises(BrokerExecutionConflictError, match="unavailable"):
        _heartbeat_deadline(agent, now + timedelta(seconds=3))
    agent.health_snapshot["execution_constraint_schemas"] = []
    with pytest.raises(BrokerExecutionConflictError, match="unavailable"):
        _heartbeat_deadline(agent, now)
    agent.qmt_connected = False
    with pytest.raises(BrokerExecutionConflictError, match="offline"):
        _heartbeat_deadline(agent, now)


def test_capacity_checks_use_available_cash_sellable_quantity_and_all_held_market_values():
    now = timezone.now()
    holding = SignedPosition("X", Decimal(10), Decimal(2), Decimal(100))
    report = SignedBrokerBalances(
        1,
        1,
        "account-hash",
        1,
        uuid4(),
        1,
        now,
        now,
        120,
        "CNY",
        Decimal(20),
        Decimal(5),
        Decimal(125),
        Decimal(100),
        (holding,),
        "receipt-hash",
        "immutable signed report",
    )
    binding = BrokerAccountBindingModel(max_position_count=1, max_single_order_amount=100)

    def check(*, side="BUY", quantity=1, code="X", balances=report):
        return _order_symbol_value(
            report=balances,
            reservations=OrderReservations(
                Decimal(0), Decimal(0), Decimal(0), frozenset(), Decimal(0)
            ),
            estimated_buy_fee=Decimal(0),
            binding=binding,
            asset_code=code,
            side=side,
            quantity=Decimal(quantity),
            limit_price=Decimal(10),
        )

    assert check() == 100 and check(side="SELL", quantity=2) == 100
    for reason, changes in (
        ("cash_insufficient", {"quantity": 3}),
        ("position_count", {"code": "Y"}),
        ("order_amount_limit", {"quantity": 11}),
        ("sellable_insufficient", {"quantity": 3, "side": "SELL"}),
        ("sellable_insufficient", {"code": "Y", "side": "SELL"}),
        (
            "position_value_unavailable",
            {"balances": replace(report, positions=(replace(holding, market_value=Decimal(0)),))},
        ),
    ):
        with pytest.raises(BrokerExecutionConflictError, match=reason):
            check(**changes)
