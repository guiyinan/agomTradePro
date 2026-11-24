"""Live order resource exposure, including native concurrent wins for cash and sellable units."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.benchmark_day_source_composition import (
    SignedBrokerBalances,
    SignedPosition,
)
from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAgentModel,
    LiveOrderModel,
)
from apps.broker_execution.infrastructure.order_risk_reservations import read_order_reservations
from apps.broker_execution.signed_account_risk_composition import _order_symbol_value
from tests.component.broker_execution.test_agent_checkpoint_concurrency import (
    _after_blocking_commit,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)


def _setup():
    user = get_user_model().objects.create_user(username=str(uuid4()))
    agent = BrokerAgentModel.objects.create(
        user=user, agent_id=str(uuid4()), display_name="capacity"
    )
    binding = BrokerAccountBindingModel.objects.create(
        user=user,
        account_id=27,
        agent=agent,
        broker_account_ref="capacity-account",
        max_single_order_amount=1000,
        max_position_count=10,
    )
    return user, agent, binding


def _order(owner, agent, *, fee="1.00", **overrides):
    from tests.component.broker_execution.test_plan_order_binding_repository import (
        NOW,
        _binding,
        _payload,
        _repository,
    )

    values = {
        "user": owner,
        "agent": agent,
        "account_id": 27,
        "client_order_id": uuid4(),
        "asset_code": "X",
        "side": "BUY",
        "limit_price": Decimal(10),
        "quantity": Decimal(6),
        "status": "READY",
        **overrides,
    }
    if values["side"] == "BUY" and "authority_pin" not in values:
        identifier = str(values["client_order_id"])
        plan = _binding(
            binding_id=identifier,
            order_artifact_id=identifier,
            broker_account_id=values["account_id"],
            plan_order_payload_json=_payload(
                asset_code=values["asset_code"],
                quantity=int(values["quantity"]),
                reference_price=str(values["limit_price"]),
                estimated_fee=fee,
            ),
        )
        repository = _repository()
        with repository.atomic():
            repository.append(plan, expected_predecessor_hash=None, recorded_at=NOW)
        values["authority_pin"] = {
            "plan_binding_hash": plan.content_hash,
            "order_id": identifier,
            "order_version": str(plan.order_version),
            "account_id": str(plan.broker_account_id),
            "plan_id": plan.portfolio_plan_id,
            "plan_version": str(plan.portfolio_plan_version),
            "plan_approval_hash": plan.portfolio_receipt_content_hash,
            "plan_order_hash": plan.plan_order_content_hash,
            "order_artifact_hash": plan.order_artifact_content_hash,
        }
    return LiveOrderModel.objects.create(**values)


@pytest.mark.django_db
def test_reservations_bind_owner_and_account_across_agents_and_wait_for_post_fill_sample():
    owner, agent, _ = _setup()
    other = get_user_model().objects.create_user(username=str(uuid4()))
    other_agent = BrokerAgentModel.objects.create(
        user=owner, agent_id=str(uuid4()), display_name="old binding"
    )
    current = _order(owner, agent)
    _order(other, agent)
    _order(owner, other_agent, account_id=232)
    buy = _order(owner, other_agent, asset_code="Y", status="PARTIALLY_FILLED", filled_quantity=2)
    sell = _order(owner, agent, side="SELL", status="CANCEL_PENDING", filled_quantity=2)
    _order(owner, agent, side="SELL", asset_code="Y")
    _order(owner, agent, status="REJECTED")

    def read(start):
        return read_order_reservations(
            user_id=owner.pk,
            account_id=27,
            client_order_id=current.client_order_id,
            asset_code="X",
            sampling_challenge_at=start,
            using="default",
        )

    earlier = timezone.now() - timedelta(minutes=1)
    before = read(earlier)
    assert (
        before.buy_amount,
        before.sell_quantity,
        before.symbol_buy_amount,
        before.buy_symbols,
    ) == (60, 6, 0, {"Y"})
    current_sample = timezone.now()
    captured = read(current_sample)
    assert before.buy_estimated_fees == captured.buy_estimated_fees == Decimal(1)
    assert (captured.buy_amount, captured.sell_quantity) == (40, 4)
    sell.status = "CANCELED"
    sell.save()
    assert read(current_sample).sell_quantity == 6
    assert read(timezone.now()).sell_quantity == 0
    with pytest.raises(BrokerExecutionConflictError, match="sampling_challenge_required"):
        read(None)
    buy.status = "RECONCILIATION_REQUIRED"
    buy.save()
    assert read(timezone.now()).buy_amount == 60
    buy.status = "FILLED"
    buy.filled_quantity = 6
    buy.save()
    assert read(earlier).buy_amount == 60
    assert read(timezone.now()).buy_amount == 0


@pytest.mark.django_db
def test_whole_estimated_buy_fee_is_reserved_and_an_unsealed_legacy_buy_fails_closed():
    owner, agent, binding = _setup()
    _order(owner, agent, fee="1.00")
    now = timezone.now()
    current_id = uuid4()

    def read():
        return read_order_reservations(
            user_id=owner.pk,
            account_id=27,
            client_order_id=current_id,
            asset_code="X",
            sampling_challenge_at=now,
            using="default",
        )

    exposure = read()
    assert (exposure.buy_amount, exposure.buy_estimated_fees) == (60, 1)
    report = SignedBrokerBalances(
        27,
        owner.pk,
        "account",
        1,
        uuid4(),
        agent.pk,
        now,
        now,
        120,
        "CNY",
        Decimal(100),
        Decimal(0),
        Decimal(100),
        Decimal(0),
        (),
        "hash",
        "fixture",
        now,
    )

    def capacity(proposed_fee):
        return _order_symbol_value(
            report=report,
            binding=binding,
            asset_code="X",
            side="BUY",
            quantity=Decimal(4),
            limit_price=Decimal("9.75"),
            estimated_buy_fee=proposed_fee,
            reservations=exposure,
        )

    assert capacity(Decimal(0)) == 60
    with pytest.raises(BrokerExecutionConflictError, match="cash_insufficient"):
        capacity(Decimal(".01"))
    _order(owner, agent, authority_pin={})
    with pytest.raises(BrokerExecutionConflictError, match="plan_fee_unavailable"):
        read()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_binding_wait_rereads_committed_peer_before_spending_same_resources(side):
    if connection.vendor != "postgresql":
        pytest.skip("requires an observed native PostgreSQL row-lock wait")
    owner, agent, binding = _setup()
    first, second = uuid4(), uuid4()
    now = timezone.now()
    report = SignedBrokerBalances(
        27,
        owner.pk,
        "account",
        1,
        uuid4(),
        agent.pk,
        now,
        now,
        120,
        "CNY",
        Decimal(100),
        Decimal(0),
        Decimal(200),
        Decimal(100),
        (SignedPosition("X", Decimal(10), Decimal(10), Decimal(100)),),
        "hash",
        "fixture",
        now,
    )

    def attempt(order_id):
        with transaction.atomic():
            locked = BrokerAccountBindingModel.objects.select_for_update().get(pk=binding.pk)
            reserved = read_order_reservations(
                user_id=owner.pk,
                account_id=27,
                client_order_id=order_id,
                asset_code="X",
                sampling_challenge_at=report.sampling_challenge_at,
                using="default",
            )
            _order_symbol_value(
                report=report,
                binding=locked,
                asset_code="X",
                side=side,
                quantity=Decimal(6),
                limit_price=Decimal(10),
                reservations=reserved,
                estimated_buy_fee=Decimal(1) if side == "BUY" else Decimal(0),
            )
            _order(owner, agent, side=side, client_order_id=order_id)
            return True

    def loser():
        with pytest.raises(
            BrokerExecutionConflictError,
            match="cash_insufficient" if side == "BUY" else "sellable_insufficient",
        ):
            attempt(second)
        return True

    assert _after_blocking_commit(lambda: attempt(first), loser)
    assert list(
        LiveOrderModel.objects.filter(user=owner, account_id=binding.account_id).values_list(
            "client_order_id", flat=True
        )
    ) == [first]
