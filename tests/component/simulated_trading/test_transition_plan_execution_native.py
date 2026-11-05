"""Native owner execution of one exact Portfolio plan revision.

Plan-source, policy, risk and preparation JSON facts below are explicitly
synthetic component inputs. The Owner order market, current risk guard, account
repository, reservation writer, fill receipt chain, settlement proof, history
reader and PostgreSQL row locks remain the real local implementations.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction

from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanRevisionBlocked,
    TransitionPlanRevisionCorruption,
)
from apps.portfolio.domain.entities import OrderDraft, TransitionPlan
from apps.portfolio.domain.transition_plan_revision import (
    TransitionPlanOrderSpecification,
    TransitionPlanRevision,
    TransitionPlanRevisionPreparation,
    build_transition_plan_revision,
)
from apps.portfolio.domain.transition_plan_revision_basis import (
    TransitionPlanBasis,
    TransitionPlanPolicyBinding,
    TransitionPlanPositionBinding,
    TransitionPlanRiskBinding,
    TransitionPlanSourceBinding,
)
from apps.portfolio.domain.transition_plan_revision_support import (
    _canonical_hash,
    _date_text,
    _datetime_text,
)
from apps.portfolio.infrastructure.transition_plan_revision_repository import (
    DjangoTransitionPlanRevisionRepository,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.manual_trade_execution import ManualSimulatedTradeRequest
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.application.owner_order_submission import OwnerOrderSubmissionUseCase
from apps.simulated_trading.application.rebalance_journey_public import (
    RebalanceJourneyAccessDenied,
)
from apps.simulated_trading.application.transition_plan_execution import (
    PlanOrderPreview,
    PlanOrderPreviewCommand,
    PreviewTransitionPlanOrderUseCase,
)
from apps.simulated_trading.application.transition_plan_execution_progress import (
    GetTransitionPlanExecutionProgressUseCase,
    PlanExecutionProgressQuery,
    TransitionPlanExecutionProgress,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    decode_order_reservation,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.rebalance_resource_snapshot_repository import (
    DjangoRebalanceResourceSnapshotRepository,
)
from apps.simulated_trading.infrastructure.transition_plan_execution_history_repository import (
    DjangoTransitionPlanExecutionHistoryRepository,
)
from apps.simulated_trading.owner_order_submission_composition import (
    build_owner_order_submission_use_case,
)
from apps.simulated_trading.transition_plan_journey_composition import (
    build_transition_plan_exact_reader,
    build_transition_plan_locked_guard,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import AS_OF as AS_OF
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    ASSET_CODE as ASSET_CODE,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    SECURITY_ID as SECURITY_ID,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _clear_runtime_profile_history as _clear_runtime_profile_history,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _freeze_auto_fixture_knowledge_clocks as _freeze_auto_fixture_knowledge_clocks,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _persist_sell_position as _persist_sell_position,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _QualifiedCallerContext as _QualifiedCallerContext,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    persisted_source_snapshot as persisted_source_snapshot,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    qualified_caller_context as qualified_caller_context,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _FixedClock,
)
from tests.component.simulated_trading.test_owner_order_submission_api import (
    public_order_context as public_order_context,
)
from tests.support.ash03_auto_calendar_clock_v2 import (
    advance_auto_uow_fixture_clocks,
    advance_auto_uow_fixture_read_clock,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(transaction=True)

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64


@dataclass(frozen=True, slots=True)
class _SyntheticCurrentPolicyPins:
    """Revalidate the exact synthetic policy digests used by this test revision."""

    expected_hashes: tuple[tuple[str, str], ...]

    def validate_current_policy_pins(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> None:
        """Reject any policy pin drift; do not issue plan or trade authority."""

        del as_of
        current = (
            ("risk_report", revision.basis.risk.report_content_hash),
            ("risk_binding", revision.basis.risk.binding_hash),
            ("fee_policy", revision.basis.fee_policy.content_hash or ""),
            ("quantity_rule", revision.basis.quantity_rule.content_hash or ""),
            ("settlement_rule", revision.basis.settlement_rule.content_hash or ""),
            ("execution_calendar", revision.basis.execution_calendar.content_hash or ""),
        )
        if current != self.expected_hashes:
            raise TransitionPlanRevisionBlocked(
                "synthetic current policy pins changed",
                code="TRANSITION_PLAN_POLICY_PINS_CHANGED",
            )


def _policy_binding(
    kind: str, *, as_of: datetime, expires_at: datetime
) -> TransitionPlanPolicyBinding:
    """Build one explicit, short-lived synthetic policy pin for the plan fixture."""

    return TransitionPlanPolicyBinding(
        kind=kind,
        status="qualified",
        reference_id=f"synthetic-{kind}-ref",
        version="fixture-v1",
        content_hash=_HASH_A,
        effective_at=as_of - timedelta(minutes=1),
        known_at=as_of - timedelta(minutes=1),
        valid_until=expires_at,
    )


def _build_revision(
    *,
    context: _QualifiedCallerContext,
    position_quantity: Decimal,
    prepared_at: datetime = AS_OF,
    expires_at: datetime | None = None,
    estimated_fee: Decimal = Decimal("0"),
) -> TransitionPlanRevision:
    """Create a self-consistent synthetic immutable plan with canonical embedded evidence."""

    account = context.account
    owner_id = context.owner_id
    expiry = expires_at or prepared_at + timedelta(minutes=4)
    portfolio_as_of = prepared_at - timedelta(seconds=1)
    if type(account.current_cash) is not Decimal:
        raise AssertionError("the isolated test account must expose an exact Decimal cash value")
    cash = account.current_cash
    reference_price = Decimal("100.00")
    position_value = position_quantity * reference_price
    source = TransitionPlanSourceBinding(
        kind="valuation",
        asset_code=ASSET_CODE,
        security_id=SECURITY_ID,
        source_id="synthetic-plan-valuation",
        source_record_id=f"synthetic-plan-valuation-{account.pk}",
        manifest_sha256=_HASH_B,
        body_sha256=_HASH_C,
        observation_precision="timestamp",
        observed_at=prepared_at - timedelta(minutes=1),
        observed_on=None,
        available_at=prepared_at - timedelta(seconds=30),
        known_at=prepared_at - timedelta(seconds=30),
        decision_cutoff=prepared_at,
        decision_date_cutoff=None,
        source_valid_until=prepared_at + timedelta(minutes=10),
        admission_until=expiry,
        qualification_proof_hash=None,
        source_purpose="valuation_snapshot",
        requested_purpose="transition_plan",
        allowed_purposes=("transition_plan",),
        restrictions=("synthetic_test_only",),
        coverage_status="complete",
        qualified=True,
    )
    source_payload = source.to_payload()
    source_binding_hash = _canonical_hash(source_payload)
    positions = (
        TransitionPlanPositionBinding(
            asset_code=ASSET_CODE,
            security_id=SECURITY_ID,
            quantity=position_quantity,
            available_quantity=position_quantity,
            target_weight=None,
            target_quantity=None,
            reference_price=reference_price,
            market_value=position_value,
            quantity_unit="share",
            money_unit="CNY",
            source_binding_hashes=(source_binding_hash,),
        ),
    )
    resource_payload: dict[str, object] = {
        "scope": "synthetic_native_component_fixture",
        "account_id": account.pk,
        "owner_user_id": owner_id,
        "cash": format(cash, "f"),
        "money_unit": "CNY",
        "positions": [row.to_payload() for row in positions],
    }
    portfolio_hash = _canonical_hash(resource_payload)
    source_evidence_hash = _canonical_hash({"source_bindings": [source_payload]})
    target_payload: dict[str, object] = {
        "target_kind": "synthetic_zero_position",
        "positions": [],
        "cash_weight": "1",
    }
    target_hash = _canonical_hash(target_payload)
    selection_id = f"synthetic-selection-{account.pk}"
    selection_hash = _canonical_hash(
        {"selection_id": selection_id, "target_content_hash": target_hash}
    )
    decision_payload: dict[str, object] = {
        "portfolio_snapshot_id": f"synthetic-portfolio-{account.pk}",
        "portfolio_snapshot_hash": portfolio_hash,
        "target_portfolio_id": f"synthetic-target-{account.pk}",
        "target_content_hash": target_hash,
        "selection_id": selection_id,
        "selection_hash": selection_hash,
    }
    decision_hash = _canonical_hash(decision_payload)
    policies = {
        "planning_policy": TransitionPlanPolicyBinding(
            kind="planning_policy",
            status="not_applicable",
            reference_id=None,
            version=None,
            content_hash=None,
            effective_at=None,
            known_at=None,
            valid_until=None,
            reason_code="synthetic_test_has_no_separate_planning_policy",
        ),
        "fee_policy": _policy_binding("fee_policy", as_of=prepared_at, expires_at=expiry),
        "quantity_rule": _policy_binding("quantity_rule", as_of=prepared_at, expires_at=expiry),
        "settlement_rule": _policy_binding("settlement_rule", as_of=prepared_at, expires_at=expiry),
        "execution_calendar": _policy_binding(
            "execution_calendar", as_of=prepared_at, expires_at=expiry
        ),
    }
    risk = TransitionPlanRiskBinding(
        report_content_hash=_HASH_C,
        binding_hash=_HASH_D,
        outcome="allowed",
        must_not_use_for_decision=False,
    )
    business_date = prepared_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
    basis_evidence = {
        "schema": "ash08.plan_preparation.v1",
        "portfolio_snapshot": {
            "id": decision_payload["portfolio_snapshot_id"],
            "content_hash": portfolio_hash,
            "source_evidence_hash": source_evidence_hash,
            "as_of": _datetime_text(portfolio_as_of),
            "resources": resource_payload,
        },
        "decision_snapshot": {
            "id": f"synthetic-decision-{account.pk}",
            "content_hash": decision_hash,
            "payload": decision_payload,
        },
        "target": {
            "id": decision_payload["target_portfolio_id"],
            "content_hash": target_hash,
            "selection_id": selection_id,
            "selection_hash": selection_hash,
            "payload": target_payload,
        },
        "policy_bindings": {key: value.to_payload() for key, value in policies.items()},
        "risk": risk.to_payload(),
        "source_bindings": [source_payload],
        "positions": {
            "current": [row.to_payload() for row in positions],
            "target": [],
        },
        "business_date": _date_text(business_date),
        "execution_session": _date_text(business_date),
        "prepared_at": _datetime_text(prepared_at),
    }
    evidence_json = json.dumps(
        basis_evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    basis = TransitionPlanBasis(
        account_id=account.pk,
        owner_user_id=owner_id,
        requested_by_user_id=owner_id,
        money_unit="CNY",
        portfolio_snapshot_id=str(decision_payload["portfolio_snapshot_id"]),
        portfolio_snapshot_hash=portfolio_hash,
        portfolio_snapshot_as_of=portfolio_as_of,
        portfolio_source_evidence_hash=source_evidence_hash,
        decision_snapshot_id=f"synthetic-decision-{account.pk}",
        decision_snapshot_hash=decision_hash,
        target_portfolio_id=str(decision_payload["target_portfolio_id"]),
        target_content_hash=target_hash,
        selection_id=selection_id,
        selection_hash=selection_hash,
        planning_policy=policies["planning_policy"],
        risk=risk,
        fee_policy=policies["fee_policy"],
        quantity_rule=policies["quantity_rule"],
        settlement_rule=policies["settlement_rule"],
        execution_calendar=policies["execution_calendar"],
        source_bindings=(source,),
        current_positions=positions,
        target_positions=(),
        business_date=business_date,
        execution_session=business_date,
        prepared_at=prepared_at,
        valid_until=expiry,
        preparation_evidence_json=evidence_json,
    )
    plan = TransitionPlan(
        plan_id="pending-plan-id",
        idempotency_key=f"synthetic-transition-plan-{account.pk}",
        account_id=str(account.pk),
        decision_snapshot_id=basis.decision_snapshot_id,
        portfolio_snapshot_id=basis.portfolio_snapshot_id,
        target_portfolio_id=basis.target_portfolio_id,
        as_of_time=portfolio_as_of,
        expires_at=expiry,
        orders=(
            OrderDraft(
                asset_code=ASSET_CODE,
                side="sell",
                quantity=300,
                reference_price=reference_price,
                estimated_fee=estimated_fee,
                status="DRAFT",
            ),
        ),
        constraints=(),
        cash_before=cash,
        cash_after=cash + Decimal("30000") - estimated_fee,
        status="DRAFT",
        metadata={"planning_policy_version": "not_applicable"},
    )
    preparation = TransitionPlanRevisionPreparation(
        plan=plan,
        basis=basis,
        family_id=f"synthetic-family-{account.pk}",
        root_plan_id=None,
        version=1,
        parent_plan_id=None,
        parent_version=None,
        parent_revision_hash=None,
        order_specifications=(
            TransitionPlanOrderSpecification(
                ordinal=0,
                asset_code=ASSET_CODE,
                security_id=SECURITY_ID,
                asset_type="equity",
                classification_content_hash=_HASH_A,
                quantity_unit="share",
                money_unit="CNY",
            ),
        ),
    )
    return build_transition_plan_revision(preparation)


def _persist_revision(context: _QualifiedCallerContext) -> TransitionPlanRevision:
    """Persist one exact synthetic revision through the existing Portfolio repository."""

    position = _persist_sell_position(context.account)
    context.account.current_market_value = position.market_value
    context.account.total_value = context.account.current_cash + position.market_value
    context.account.save(
        update_fields=[
            "current_market_value",
            "total_value",
            "cash_known",
            "cash_reconciliation_status",
        ]
    )
    revision = _build_revision(
        context=context,
        position_quantity=Decimal(position.quantity),
    )
    saved = DjangoTransitionPlanRevisionRepository(using="default").append_initial(
        revision,
        idempotency_key=revision.plan.idempotency_key,
    )
    return saved


@dataclass(frozen=True, slots=True)
class _PinnedPolicyReader:
    """Strict test validator for this revision's synthetic current policy identities."""

    hashes: tuple[tuple[str, str], ...]

    def validate_current_policy_pins(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> None:
        """Block when any policy digest differs from the explicitly expected fixture."""

        _SyntheticCurrentPolicyPins(self.hashes).validate_current_policy_pins(
            revision,
            as_of=as_of,
        )


@dataclass
class _AtomicDepthPolicyReader:
    """Record the real transaction depth before delegating policy validation."""

    delegate: _PinnedPolicyReader
    observed_depths: list[int]

    def validate_current_policy_pins(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> None:
        """Observe the active default transaction, then keep the real test pin check."""

        self.observed_depths.append(len(connection.atomic_blocks))
        self.delegate.validate_current_policy_pins(revision, as_of=as_of)


def _current_synthetic_policy_hashes() -> tuple[tuple[str, str], ...]:
    """Return the independently declared current synthetic policy snapshot pins."""

    return (
        ("risk_report", _HASH_C),
        ("risk_binding", _HASH_D),
        ("fee_policy", _HASH_A),
        ("quantity_rule", _HASH_A),
        ("settlement_rule", _HASH_A),
        ("execution_calendar", _HASH_A),
    )


def _plan_services(
    revision: TransitionPlanRevision,
) -> tuple[OwnerOrderSubmissionUseCase, PreviewTransitionPlanOrderUseCase]:
    """Compose actual exact plan readers, revision guard, and ordinary Owner use case."""

    clock = _FixedClock(AS_OF)
    exact_reader = build_transition_plan_exact_reader(using="default")
    guard = build_transition_plan_locked_guard(
        using="default",
        current_policy_pins_validator=_PinnedPolicyReader(_current_synthetic_policy_hashes()),
    )
    order_service = build_owner_order_submission_use_case(
        market_purpose="local_simulation_only",
        transition_plan_guard=guard,
    )
    preview_service = PreviewTransitionPlanOrderUseCase(
        revision_reader=exact_reader,
        order_submission=order_service,
        clock=clock,
    )
    return order_service, preview_service


def _preview_command(
    revision: TransitionPlanRevision,
    context: _QualifiedCallerContext,
    *,
    attempt: str,
) -> PlanOrderPreviewCommand:
    """Build an explicit exact-line action request; the plan row supplies all terms."""

    order = revision.orders[0]
    return PlanOrderPreviewCommand(
        actor_user_id=context.owner_id,
        account_id=context.account.pk,
        plan_id=revision.identity.plan_id,
        plan_version=revision.identity.version,
        expected_revision_hash=revision.identity.revision_hash,
        order_ordinal=order.ordinal,
        expected_order_content_hash=order.order_content_hash,
        expected_plan_order_binding_id=order.plan_order_binding_id,
        action_attempt_key=attempt,
        quantity=Decimal("300"),
        price=Decimal("10.00"),
        reason="synthetic Native plan-bound partial-fill case",
    )


def _read_progress(
    revision: TransitionPlanRevision,
    context: _QualifiedCallerContext,
    *,
    as_of: datetime,
) -> TransitionPlanExecutionProgress:
    """Read owner progress using the exact-revision and real resource/history repositories."""

    exact_reader = build_transition_plan_exact_reader(using="default")
    return GetTransitionPlanExecutionProgressUseCase(
        revision_reader=exact_reader,
        family_head_reader=DjangoTransitionPlanRevisionRepository(using="default"),
        history_reader=DjangoTransitionPlanExecutionHistoryRepository(using="default"),
        resource_reader=DjangoRebalanceResourceSnapshotRepository(using="default"),
        clock=_FixedClock(as_of),
    ).execute(
        PlanExecutionProgressQuery(
            actor_user_id=context.owner_id,
            account_id=context.account.pk,
            plan_id=revision.identity.plan_id,
            plan_version=revision.identity.version,
            expected_revision_hash=revision.identity.revision_hash,
        )
    )


def test_native_owner_plan_order_reserves_fills_cancels_and_reconciles_exact_progress(
    public_order_context: tuple[_QualifiedCallerContext, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    django_db_use_migrations: bool,
) -> None:
    """One ordinary Owner action remains bound to its immutable plan through fill/cancel."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip("plan-bound order locking requires the isolated migrated PostgreSQL database")
    assert_native_postgres_test_database()
    context, capture_calls = public_order_context
    revision = _persist_revision(context)
    owner = get_user_model().objects.get(pk=context.owner_id)
    assert owner.is_staff is False
    assert owner.is_superuser is False
    cash_before = context.account.current_cash
    order_service, preview_service = _plan_services(revision)
    before_reservations = SimulatedOrderReservationModel.objects.filter(
        account_id=context.account.pk
    ).count()
    plan_preview: PlanOrderPreview = preview_service.execute(
        _preview_command(revision, context, attempt="native-attempt-001")
    )
    assert plan_preview.binding.revision_hash == revision.identity.revision_hash
    assert plan_preview.binding.order_content_hash == revision.orders[0].order_content_hash
    assert plan_preview.preview.result.reservation.status.value == "active"
    assert (
        SimulatedOrderReservationModel.objects.filter(account_id=context.account.pk).count()
        == before_reservations
    )
    assert capture_calls == [ASSET_CODE]

    confirmed = order_service.confirm(
        account_id=context.account.pk,
        user_id=context.owner_id,
        token=plan_preview.preview.token,
        confirmed=True,
        expected_key=plan_preview.preview.result.reservation.identity.idempotency_key,
        market_purpose="local_simulation_only",
    )
    row = SimulatedOrderReservationModel.objects.get(pk=confirmed.order_id)
    assert row.quantity == Decimal("300")
    assert (
        row.plan_snapshot["transition_plan_binding"]["binding"]["revision_hash"]
        == revision.identity.revision_hash
    )
    assert (
        row.plan_snapshot["transition_plan_binding"]["binding"]["action_attempt_key"]
        == "native-attempt-001"
    )
    replay = order_service.confirm(
        account_id=context.account.pk,
        user_id=context.owner_id,
        token=plan_preview.preview.token,
        confirmed=True,
        expected_key=plan_preview.preview.result.reservation.identity.idempotency_key,
        market_purpose="local_simulation_only",
    )
    assert replay.order_id == confirmed.order_id
    assert replay.result.replayed is True
    assert (
        SimulatedOrderReservationModel.objects.filter(account_id=context.account.pk).count()
        == before_reservations + 1
    )

    before_fill_as_of = AS_OF + timedelta(seconds=1)
    advance_auto_uow_fixture_read_clock(monkeypatch, as_of=before_fill_as_of)
    before_fill = _read_progress(revision, context, as_of=before_fill_as_of)
    assert before_fill.read_status == "complete"
    assert before_fill.account is not None
    assert before_fill.account.exact_cash == cash_before
    assert before_fill.account.available_cash_after_holds == cash_before
    assert before_fill.orders[0].outcome == "in_flight"
    assert before_fill.orders[0].in_flight_quantity == Decimal("300")
    assert before_fill.orders[0].active_sell_quantity == Decimal("300")
    assert before_fill.orders[0].released_quantity == Decimal("0")
    assert SimulatedTradeModel.objects.filter(account_id=context.account.pk).count() == 0

    fill_at = AS_OF + timedelta(seconds=1)
    event = LocalSimulatedFillEventV1(
        source_namespace="test.fixture.ash08-native-plan-fill",
        source_version="fixture-v1",
        source_event_id="native-partial-001",
        event_payload_hash=sha256(b"synthetic ASH08 partial fill event").hexdigest(),
        source_snapshot_id="synthetic-native-fill-snapshot",
        source_snapshot_hash=sha256(b"synthetic native fill snapshot").hexdigest(),
        reservation_id=row.pk,
        account_id=context.account.pk,
        user_id=context.owner_id,
        order_idempotency_key=row.idempotency_key,
        intent_payload_hash=row.intent_payload_hash,
        reservation_request_hash=row.reservation_request_hash,
        plan_snapshot_hash=row.plan_snapshot_hash,
        security_id=row.security_id,
        asset_code=row.asset_code,
        side=SimulatedTradeSide.SELL,
        event_kind=LocalSimulatedFillEventKind.FILL,
        quantity=Decimal("100"),
        price=Decimal("10.00"),
        occurred_at=fill_at,
        source_observed_at=fill_at,
        source_available_at=fill_at,
        recorded_at=fill_at,
    )
    settlement = build_order_fill_settlement_proof(
        calendar_evidence=context.uow.calendar_evidence,
        calendar_read_cutoff=fill_at,
        fill_occurred_at=fill_at,
        settlement_exchange=context.uow.calendar_evidence.snapshot.exchange,
        settlement_lag_sessions=context.uow.rule_bundle.settlement_policy_v1.settlement_lag_sessions,
    )
    fill_repo = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(event, []),
        using="default",
    )
    fill_result = fill_repo.apply_fill_event(
        event=event,
        expected_event_payload_hash=event.event_payload_hash,
        settlement_proof=settlement,
        clock=_FixedClock(fill_at),
    )
    assert fill_result.replayed is False
    assert fill_result.reservation.filled_quantity == Decimal("100")

    advance_auto_uow_fixture_clocks(monkeypatch, as_of=fill_at + timedelta(seconds=1))
    from apps.simulated_trading.application.order_reservation import (
        CancelSimulatedOrderReservationUseCase,
    )
    from apps.simulated_trading.infrastructure.order_reservation_repository import (
        DjangoSimulatedOrderReservationRepository,
    )

    cancelled = CancelSimulatedOrderReservationUseCase(
        repository=DjangoSimulatedOrderReservationRepository(using="default"),
        clock=_FixedClock(fill_at + timedelta(seconds=1)),
    ).execute(
        account_id=context.account.pk,
        user_id=context.owner_id,
        idempotency_key=row.idempotency_key,
    )
    assert cancelled.filled_quantity == Decimal("100")
    assert cancelled.quantity - cancelled.filled_quantity == Decimal("200")
    assert capture_calls == [ASSET_CODE]

    from apps.simulated_trading.application.order_history import ReadOrderHistoryUseCase
    from apps.simulated_trading.infrastructure.order_history_repository import (
        DjangoOrderHistoryRepository,
    )

    history = ReadOrderHistoryUseCase(
        reader=DjangoOrderHistoryRepository(using="default"),
        clock=_FixedClock(fill_at + timedelta(seconds=1)),
    )
    orders_page = history.read_orders(account_id=context.account.pk, user_id=context.owner_id)
    history_order = next(order for order in orders_page.orders if order.order_id == row.pk)
    assert history_order.status.value == "cancelled"
    assert history_order.quantity == Decimal("300")
    assert history_order.filled_quantity == Decimal("100")
    fills_page = history.read_fills(
        account_id=context.account.pk,
        user_id=context.owner_id,
        order_id=row.pk,
    )
    assert len(fills_page.fills) == 1
    assert fills_page.fills[0].quantity == Decimal("100")
    assert fills_page.fills[0].verification_status == "single_receipt_verified"

    context.account.refresh_from_db()
    row.refresh_from_db()
    ledger_before_progress = (
        context.account.current_cash,
        PositionModel.objects.get(account_id=context.account.pk, asset_code=ASSET_CODE).quantity,
        row.status,
        row.filled_quantity,
        row.shares_released,
        SimulatedTradeModel.objects.filter(account_id=context.account.pk).count(),
    )
    progress = _read_progress(revision, context, as_of=fill_at + timedelta(seconds=1))
    assert progress.read_status == "blocked"
    assert progress.current_head is True
    assert progress.account is not None
    assert progress.account.exact_cash is not None
    assert len(progress.orders) == 1
    line = progress.orders[0]
    assert line.filled_quantity == Decimal("100")
    assert line.released_quantity == Decimal("200")
    assert line.actual_fees_paid is not None
    assert line.actual_fees_paid > Decimal("0")
    assert line.fees_complete is True
    assert line.requires_successor is True
    assert line.can_preview is False
    assert line.can_cancel is False
    assert line.cancelled_order_ids == (row.pk,)
    assert SimulatedTradeSide.SELL.value == row.side
    context.account.refresh_from_db()
    row.refresh_from_db()
    ledger_after_progress = (
        context.account.current_cash,
        PositionModel.objects.get(account_id=context.account.pk, asset_code=ASSET_CODE).quantity,
        row.status,
        row.filled_quantity,
        row.shares_released,
        SimulatedTradeModel.objects.filter(account_id=context.account.pk).count(),
    )
    assert ledger_after_progress == ledger_before_progress


def test_native_plan_context_rejects_foreign_account_expiry_and_policy_drift_without_write(
    public_order_context: tuple[_QualifiedCallerContext, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    django_db_use_migrations: bool,
) -> None:
    """Context pins cannot bypass owner scope, plan expiry, or current policy comparison."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip("plan-bound qualification requires the isolated migrated PostgreSQL database")
    assert_native_postgres_test_database()
    context, capture_calls = public_order_context
    revision = _persist_revision(context)
    context.account.refresh_from_db()
    position = PositionModel.objects.get(account_id=context.account.pk, asset_code=ASSET_CODE)
    ledger_before = (
        context.account.current_cash,
        position.quantity,
        SimulatedTradeModel.objects.filter(account_id=context.account.pk).count(),
        SimulatedOrderReservationModel.objects.filter(account_id=context.account.pk).count(),
    )
    order_service, preview_service = _plan_services(revision)
    initial_count = SimulatedOrderReservationModel.objects.filter(
        account_id=context.account.pk
    ).count()

    foreign = _preview_command(revision, context, attempt="foreign-account-attempt")
    with pytest.raises(RebalanceJourneyAccessDenied):
        preview_service.execute(replace(foreign, account_id=context.account.pk + 999))

    expired_service = PreviewTransitionPlanOrderUseCase(
        revision_reader=build_transition_plan_exact_reader(using="default"),
        order_submission=order_service,
        clock=_FixedClock(revision.identity.valid_until + timedelta(seconds=1)),
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as expired:
        expired_service.execute(_preview_command(revision, context, attempt="expired-attempt"))
    assert expired.value.code == "TRANSITION_PLAN_EXPIRED"

    changed_guard = build_transition_plan_locked_guard(
        using="default",
        current_policy_pins_validator=_PinnedPolicyReader(
            (
                ("risk_report", _HASH_D),
                ("risk_binding", _HASH_D),
                ("fee_policy", _HASH_A),
                ("quantity_rule", _HASH_A),
                ("settlement_rule", _HASH_A),
                ("execution_calendar", _HASH_A),
            )
        ),
    )
    changed_order_service = build_owner_order_submission_use_case(
        market_purpose="local_simulation_only",
        transition_plan_guard=changed_guard,
    )
    preview = preview_service.execute(
        _preview_command(revision, context, attempt="policy-drift-attempt")
    )
    with pytest.raises(TransitionPlanRevisionBlocked):
        changed_order_service.confirm(
            account_id=context.account.pk,
            user_id=context.owner_id,
            token=preview.preview.token,
            confirmed=True,
            expected_key=preview.preview.result.reservation.identity.idempotency_key,
            market_purpose="local_simulation_only",
        )
    valid_guard = build_transition_plan_locked_guard(
        using="default",
        current_policy_pins_validator=_PinnedPolicyReader(_current_synthetic_policy_hashes()),
    )
    original_binding = revision.orders[0].to_execution_binding(
        revision.identity,
        owner_user_id=context.owner_id,
        action_attempt_key="classification-drift-attempt",
    )
    with pytest.raises(TransitionPlanRevisionCorruption):
        valid_guard.validate_locked_action(
            binding=replace(original_binding, classification_content_hash=_HASH_D),
            account_id=context.account.pk,
            owner_user_id=context.owner_id,
            as_of=AS_OF + timedelta(seconds=1),
        )
    with pytest.raises(TransitionPlanRevisionBlocked):
        valid_guard.validate_locked_action(
            binding=original_binding,
            account_id=context.account.pk,
            owner_user_id=context.owner_id,
            as_of=revision.identity.valid_until + timedelta(seconds=1),
        )
    with pytest.raises(TransitionPlanRevisionBlocked):
        valid_guard.validate_locked_action(
            binding=replace(original_binding, plan_id="another-plan-id"),
            account_id=context.account.pk,
            owner_user_id=context.owner_id,
            as_of=AS_OF + timedelta(seconds=1),
        )
    assert (
        SimulatedOrderReservationModel.objects.filter(account_id=context.account.pk).count()
        == initial_count
    )
    context.account.refresh_from_db()
    position.refresh_from_db()
    assert (
        context.account.current_cash,
        position.quantity,
        SimulatedTradeModel.objects.filter(account_id=context.account.pk).count(),
        SimulatedOrderReservationModel.objects.filter(account_id=context.account.pk).count(),
    ) == ledger_before
    assert capture_calls == [ASSET_CODE]


def test_native_locked_guard_reuses_one_outer_transaction_for_policy_validation(
    public_order_context: tuple[_QualifiedCallerContext, list[str]],
    django_db_use_migrations: bool,
) -> None:
    """Policy validation runs at one transaction depth for owned and caller-owned UoWs."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip("locked plan guard requires the isolated migrated PostgreSQL database")
    assert_native_postgres_test_database()
    context, _ = public_order_context
    revision = _persist_revision(context)
    depths: list[int] = []
    policy_reader = _AtomicDepthPolicyReader(
        delegate=_PinnedPolicyReader(_current_synthetic_policy_hashes()),
        observed_depths=depths,
    )
    guard = build_transition_plan_locked_guard(
        using="default", current_policy_pins_validator=policy_reader
    )
    binding = revision.orders[0].to_execution_binding(
        revision.identity,
        owner_user_id=context.owner_id,
        action_attempt_key="guard-transaction-boundary",
    )
    as_of = AS_OF

    owned_result = guard.validate_locked_action(
        binding=binding,
        account_id=context.account.pk,
        owner_user_id=context.owner_id,
        as_of=as_of,
    )
    assert owned_result.identity.revision_hash == revision.identity.revision_hash
    assert depths == [1]

    depths.clear()
    with transaction.atomic():
        caller_owned_result = guard.validate_locked_action(
            binding=binding,
            account_id=context.account.pk,
            owner_user_id=context.owner_id,
            as_of=as_of,
        )
        assert caller_owned_result.identity.revision_hash == revision.identity.revision_hash
        assert depths == [1]


def test_native_distinct_plan_attempts_serialize_to_one_reservation(
    public_order_context: tuple[_QualifiedCallerContext, list[str]],
    django_db_use_migrations: bool,
) -> None:
    """Two different action keys cannot create parallel holds for the same plan line."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip("concurrent plan reservation requires isolated migrated PostgreSQL")
    assert_native_postgres_test_database()
    context, capture_calls = public_order_context
    revision = _persist_revision(context)
    order_service, preview_service = _plan_services(revision)
    previews = tuple(
        preview_service.execute(
            _preview_command(revision, context, attempt=f"concurrent-attempt-{index}")
        )
        for index in (1, 2)
    )

    def confirm_one(index: int) -> tuple[str, int | str]:
        """Use a thread-local Django connection for one competing confirmation."""

        close_old_connections()
        preview = previews[index]
        try:
            result = order_service.confirm(
                account_id=context.account.pk,
                user_id=context.owner_id,
                token=preview.preview.token,
                confirmed=True,
                expected_key=preview.preview.result.reservation.identity.idempotency_key,
                market_purpose="local_simulation_only",
            )
            return "committed", result.order_id
        except SimulatedTradeExecutionBlocked as error:
            if error.code != "TRANSITION_PLAN_SUCCESSOR_REQUIRED":
                raise
            return "blocked", error.code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(confirm_one, (0, 1)))
    assert sum(outcome[0] == "committed" for outcome in outcomes) == 1
    assert (
        sum(outcome == ("blocked", "TRANSITION_PLAN_SUCCESSOR_REQUIRED") for outcome in outcomes)
        == 1
    )
    assert SimulatedOrderReservationModel.objects.filter(account_id=context.account.pk).count() == 1
    assert capture_calls == [ASSET_CODE, ASSET_CODE]


def test_native_unbound_owner_reservation_keeps_legacy_snapshot_shape_and_hash(
    public_order_context: tuple[_QualifiedCallerContext, list[str]],
    django_db_use_migrations: bool,
) -> None:
    """Plan support leaves an ordinary reservation without new nullable binding fields."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip("legacy snapshot compatibility requires isolated migrated PostgreSQL")
    assert_native_postgres_test_database()
    context, capture_calls = public_order_context
    _persist_sell_position(context.account)
    order_service = build_owner_order_submission_use_case(market_purpose="local_simulation_only")
    request = ManualSimulatedTradeRequest(
        account_id=context.account.pk,
        user_id=context.owner_id,
        idempotency_key=f"legacy-unbound-{context.account.pk}",
        asset_code=ASSET_CODE,
        asset_name=ASSET_CODE,
        asset_type="equity",
        side=SimulatedTradeSide.SELL,
        quantity=Decimal("100"),
        price=Decimal("10.00"),
        reason="synthetic legacy snapshot compatibility case",
        signal_id=None,
    )
    preview = order_service.preview(request, fee_budget=None)
    result = order_service.confirm(
        account_id=context.account.pk,
        user_id=context.owner_id,
        token=preview.token,
        confirmed=True,
        expected_key=request.idempotency_key,
        market_purpose="local_simulation_only",
    )
    row = SimulatedOrderReservationModel.objects.get(pk=result.order_id)
    original_snapshot = dict(validated_plan_snapshot(row))
    original_json = json.dumps(
        original_snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    original_hash = row.plan_snapshot_hash
    assert "transition_plan_binding" not in original_snapshot

    decoded = decode_order_reservation(row)
    reread_json = json.dumps(
        dict(validated_plan_snapshot(row)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    assert decoded.identity.idempotency_key == request.idempotency_key
    assert reread_json == original_json
    assert row.plan_snapshot_hash == original_hash
    assert capture_calls == [ASSET_CODE]
