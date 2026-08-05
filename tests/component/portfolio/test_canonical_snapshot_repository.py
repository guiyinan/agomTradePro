"""Component coverage for Portfolio canonical snapshot persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from apps.account.infrastructure.models import AccountProfileModel
from apps.portfolio.domain.canonical_snapshots import (
    BrokerFillEvidence,
    BrokerOrderEventEvidence,
    CanonicalPosition,
    build_broker_execution_evidence,
    build_canonical_cash_projection,
    build_canonical_portfolio_snapshot,
    build_canonical_positions_projection,
    build_execution_feedback,
)
from apps.portfolio.infrastructure.canonical_snapshot_models import (
    CanonicalPortfolioSnapshotModel,
    PortfolioExecutionFeedbackModel,
)
from apps.portfolio.infrastructure.canonical_snapshot_repositories import (
    DjangoCanonicalPortfolioSnapshotRepository,
    DjangoPortfolioExecutionFeedbackRepository,
)
from apps.portfolio.infrastructure.models import (
    OrderIntentModel,
    PortfolioTransitionPlanModel,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from apps.strategy.infrastructure.models import StrategyModel

NOW = datetime(2026, 8, 5, 9, tzinfo=UTC)


def _snapshot():  # type: ignore[no-untyped-def]
    return build_canonical_portfolio_snapshot(
        cash_projection=build_canonical_cash_projection(
            account_ref="account:42",
            base_currency="CNY",
            cash_balance=Decimal("5000"),
            evidence_ref="account-ledger:cash:42:v7",
            version="cash.v7",
            observed_at=NOW,
        ),
        positions_projection=build_canonical_positions_projection(
            account_ref="account:42",
            evidence_ref="portfolio-ledger:positions:42:v11",
            version="positions.v11",
            observed_at=NOW + timedelta(minutes=1),
            positions=(
                CanonicalPosition(
                    asset_code="000001.SZ",
                    quantity=Decimal("100"),
                    available_quantity=Decimal("80"),
                    market_value_base=Decimal("1023"),
                    position_source_ref="position:000001.SZ:v11",
                    position_observed_at=NOW,
                    valuation_source_ref="valuation:000001.SZ:20260805T0900Z",
                    valuation_observed_at=NOW + timedelta(seconds=30),
                ),
            ),
        ),
    )


def _portfolio_refs() -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    user = User.objects.create_user(username=f"snapshot_{unique}")
    profile = AccountProfileModel._default_manager.get(user=user)
    strategy = StrategyModel._default_manager.create(
        name=f"snapshot-strategy-{unique}",
        strategy_type="rule_based",
        version=1,
        is_active=True,
        description="snapshot feedback component test",
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        created_by=profile,
    )
    simulated_account = SimulatedAccountModel._default_manager.create(
        user=user,
        account_name=f"snapshot-account-{unique}",
        account_type="simulated",
        initial_capital=100000,
        current_cash=100000,
        current_market_value=0,
        total_value=100000,
    )
    plan_ref = f"transition-plan:{unique}"
    intent_ref = f"order-intent:{unique}"
    PortfolioTransitionPlanModel._default_manager.create(
        plan_id=plan_ref,
        account_id=str(simulated_account.pk),
        source_recommendation_ids=[],
        current_positions_snapshot=[],
        target_positions_snapshot=[],
        orders=[],
        risk_contract={},
        summary={},
        status="APPROVED",
        as_of=NOW,
    )
    OrderIntentModel._default_manager.create(
        intent_id=intent_ref,
        idempotency_key=f"intent-key:{unique}",
        strategy=strategy,
        portfolio=simulated_account,
        symbol="000001.SZ",
        side="buy",
        qty=100,
        decision_json={},
        sizing_json={},
        risk_snapshot_json={},
    )
    return plan_ref, intent_ref


@pytest.mark.django_db
def test_snapshot_repository_is_idempotent_and_preserves_source_times() -> None:
    repository = DjangoCanonicalPortfolioSnapshotRepository()
    snapshot = _snapshot()

    first = repository.append(snapshot)
    second = repository.append(snapshot)
    resolved = repository.find_at_or_before(
        account_ref="account:42",
        cutoff=NOW + timedelta(minutes=2),
    )

    assert first == second
    assert CanonicalPortfolioSnapshotModel._default_manager.count() == 1
    assert resolved is not None
    assert resolved.as_of == NOW + timedelta(minutes=1)
    assert resolved.source_evidence[0].observed_at == NOW
    assert resolved.positions[0].valuation_observed_at == NOW + timedelta(seconds=30)


@pytest.mark.django_db
def test_snapshot_model_rejects_mutation_and_deletion() -> None:
    snapshot = _snapshot()
    DjangoCanonicalPortfolioSnapshotRepository().append(snapshot)
    row = CanonicalPortfolioSnapshotModel._default_manager.get(pk=snapshot.snapshot_id)

    row.cash_balance = Decimal("999999")
    with pytest.raises(ValidationError, match="immutable"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.delete()


@pytest.mark.django_db
def test_execution_feedback_persists_stable_refs_without_cross_app_foreign_keys() -> None:
    snapshot = DjangoCanonicalPortfolioSnapshotRepository().append(_snapshot())
    plan_ref, intent_ref = _portfolio_refs()
    evidence = build_broker_execution_evidence(
        client_order_ref="client-order:1001",
        broker_order_ref="broker-order:9001",
        order_events=(
            BrokerOrderEventEvidence(
                "broker-event:1",
                "accepted",
                "submitted",
                NOW + timedelta(minutes=2),
            ),
        ),
        fills=(
            BrokerFillEvidence(
                "broker-fill:1",
                Decimal("80"),
                Decimal("10.25"),
                Decimal("2.50"),
                NOW + timedelta(minutes=3),
            ),
        ),
        reconciliation_ref="broker-reconciliation:77",
        reconciliation_observed_at=NOW + timedelta(minutes=4),
    )
    feedback = build_execution_feedback(
        portfolio_snapshot_ref=snapshot.snapshot_id,
        transition_plan_ref=plan_ref,
        order_intent_ref=intent_ref,
        planning_policy_version="a-share-policy.v4",
        asset_code="000001.SZ",
        side="buy",
        planned_quantity=Decimal("100"),
        planned_reference_price=Decimal("10"),
        planned_estimated_fee=Decimal("3"),
        broker_evidence=evidence,
    )
    repository = DjangoPortfolioExecutionFeedbackRepository()

    saved = repository.append(feedback)
    restored = repository.get(saved.feedback_id)

    assert restored == feedback
    assert repository.append(feedback) == feedback
    assert PortfolioExecutionFeedbackModel._default_manager.count() == 1
    for field_name in (
        "portfolio_snapshot_ref",
        "transition_plan_ref",
        "order_intent_ref",
        "client_order_ref",
        "broker_order_ref",
        "reconciliation_ref",
    ):
        assert PortfolioExecutionFeedbackModel._meta.get_field(field_name).remote_field is None


@pytest.mark.django_db
def test_execution_feedback_rejects_missing_portfolio_references() -> None:
    snapshot = DjangoCanonicalPortfolioSnapshotRepository().append(_snapshot())
    evidence = build_broker_execution_evidence(
        client_order_ref="client-order:missing",
        broker_order_ref="broker-order:missing",
        order_events=(
            BrokerOrderEventEvidence(
                "broker-event:missing",
                "accepted",
                "submitted",
                NOW + timedelta(minutes=2),
            ),
        ),
        fills=(),
        reconciliation_ref="broker-reconciliation:missing",
        reconciliation_observed_at=NOW + timedelta(minutes=3),
    )
    feedback = build_execution_feedback(
        portfolio_snapshot_ref=snapshot.snapshot_id,
        transition_plan_ref="missing-plan",
        order_intent_ref="missing-intent",
        planning_policy_version="a-share-policy.v4",
        asset_code="000001.SZ",
        side="buy",
        planned_quantity=Decimal("100"),
        planned_reference_price=Decimal("10"),
        planned_estimated_fee=Decimal("3"),
        broker_evidence=evidence,
    )

    with pytest.raises(ValueError, match="transition plan reference is missing"):
        DjangoPortfolioExecutionFeedbackRepository().append(feedback)
