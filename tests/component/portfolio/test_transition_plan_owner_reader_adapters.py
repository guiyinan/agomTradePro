"""Django 5.2 component coverage for Portfolio owner reader adapters."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import django
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.decision_rhythm.infrastructure.recommendation_repositories import (
    PortfolioTransitionPlanRepository as LegacyPortfolioTransitionPlanRepository,
)
from apps.portfolio.application.transition_plan_inactive_approval import (
    RegisterTransitionPlanInactiveApprovalSubject,
    RegisterTransitionPlanInactiveApprovalSubjectCommand,
    TransitionPlanInactiveApprovalSubject,
    TransitionPlanInactiveApprovalUnavailable,
)
from apps.portfolio.application.transition_plan_inactive_receipt_reader import (
    GetExactInactiveTransitionPlanApprovalReceiptQuery,
)
from apps.portfolio.application.transition_plan_order_reader import (
    GetExactActiveTransitionPlanOrderQuery,
)
from apps.portfolio.domain.entities import OrderDraft, TransitionPlan
from apps.portfolio.domain.transition_plan_integrity import (
    TransitionPlanApprovalActor,
    TransitionPlanApprovalReceipt,
    transition_plan_content_hash_v1,
)
from apps.portfolio.infrastructure.repositories import PortfolioTransitionPlanRepository
from apps.portfolio.infrastructure.transition_models import PortfolioTransitionPlanModel
from apps.portfolio.infrastructure.transition_plan_definition_provider import (
    DjangoExactTransitionPlanDefinitionProvider,
)
from apps.portfolio.infrastructure.transition_plan_inactive_approval_models import (
    TransitionPlanInactiveApprovalSubjectModel,
)
from apps.portfolio.infrastructure.transition_plan_inactive_approval_repository import (
    DjangoTransitionPlanInactiveApprovalRepository,
)
from apps.portfolio.infrastructure.transition_plan_revision_repository import (
    DjangoTransitionPlanRevisionRepository,
)
from apps.portfolio.transition_plan_owner_readers_composition import (
    build_django_transition_plan_owner_reader_runtime,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from core.integration.transition_plan_contracts import (
    CANONICAL_TRANSITION_PLAN_FAMILY,
    LEGACY_TRANSITION_PLAN_FAMILY,
    PORTFOLIO_PLAN_REVISION_FAMILY,
    PORTFOLIO_PLAN_REVISION_MARKER,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _QualifiedCallerContext,
)
from tests.component.simulated_trading.test_transition_plan_execution_native import (
    _build_revision,
)


def _actor(user_id: int) -> TransitionPlanApprovalActor:
    return TransitionPlanApprovalActor(
        actor_id=f"user:{user_id}", user_id=user_id, role="portfolio_owner"
    )


def _plan() -> TransitionPlan:
    now = timezone.now()
    return TransitionPlan(
        plan_id="owner-reader-plan-1",
        idempotency_key="owner-reader-idem-1",
        account_id="account:7",
        decision_snapshot_id="decision-1",
        portfolio_snapshot_id="portfolio-1",
        target_portfolio_id="target-1",
        as_of_time=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        orders=(
            OrderDraft(
                asset_code="600000.SH",
                side="buy",
                quantity=10,
                reference_price=Decimal("10.00"),
                estimated_fee=Decimal("1.00"),
                status="draft",
            ),
        ),
        constraints=(),
        cash_before=Decimal("1000.00"),
        cash_after=Decimal("899.00"),
        status="APPROVED",
        version=1,
        metadata={"planning_policy_version": "policy-v1"},
    )


def _revision_family_row(
    *, family: str, risk_contract: object, status: str = "DRAFT"
) -> PortfolioTransitionPlanModel:
    """Persist a row discriminator fixture without inventing a valid revision payload."""

    now = timezone.now()
    token = uuid4().hex[:12]
    return PortfolioTransitionPlanModel._default_manager.create(
        plan_id=f"ash08-compat-{token}",
        account_id="7",
        source_recommendation_ids=[],
        current_positions_snapshot=[],
        target_positions_snapshot=[],
        orders=[],
        risk_contract=risk_contract,
        summary={"cash_before": "0", "cash_after": "0"},
        status=status,
        approval_request_id="",
        plan_contract_family=family,
        idempotency_key=f"ash08-compat-key-{token}",
        decision_snapshot_id="decision-ash08-compat",
        portfolio_snapshot_id="portfolio-ash08-compat",
        target_portfolio_id="target-ash08-compat",
        expires_at=now + timedelta(hours=1),
        immutable_payload_hash="0" * 64,
        plan_version=1,
        approved_at=now if status == "APPROVED" else None,
        as_of=now - timedelta(minutes=1),
    )


def _legacy_plan_row(
    *, plan_id: str, risk_contract: object | None = None
) -> PortfolioTransitionPlanModel:
    """Persist a minimal legacy row for compatibility read tests."""

    now = timezone.now()
    token = uuid4().hex[:12]
    return PortfolioTransitionPlanModel._default_manager.create(
        plan_id=plan_id,
        account_id="7",
        source_recommendation_ids=[],
        current_positions_snapshot=[],
        target_positions_snapshot=[],
        orders=[],
        risk_contract={} if risk_contract is None else risk_contract,
        summary={},
        status="DRAFT",
        approval_request_id="",
        plan_contract_family=LEGACY_TRANSITION_PLAN_FAMILY,
        idempotency_key=f"ash08-legacy-compat-{token}",
        decision_snapshot_id="",
        portfolio_snapshot_id="",
        target_portfolio_id="",
        expires_at=None,
        immutable_payload_hash="",
        plan_version=1,
        approved_at=None,
        as_of=now - timedelta(minutes=1),
    )


@pytest.mark.django_db(transaction=True)
def test_django_owner_runtime_reads_exact_plan_row_and_identity_receipt() -> None:
    assert django.VERSION[:2] == (5, 2)
    plan = _plan()
    PortfolioTransitionPlanRepository().save(plan)
    assert PortfolioTransitionPlanRepository().get(plan.plan_id) == plan
    approved_at = timezone.now()
    PortfolioTransitionPlanModel._default_manager.filter(plan_id=plan.plan_id).update(
        approved_at=approved_at
    )
    subject = TransitionPlanInactiveApprovalSubject(
        subject_id="owner-reader-subject-1",
        subject_version="v1",
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_content_hash=PortfolioTransitionPlanModel._default_manager.get(
            plan_id=plan.plan_id
        ).immutable_payload_hash,
        account_id=plan.account_id,
        decision_snapshot_id=plan.decision_snapshot_id,
        requested_by=_actor(11),
        requested_at=approved_at,
        valid_until=plan.expires_at,
    )
    receipt = TransitionPlanApprovalReceipt(
        receipt_id="owner-reader-receipt-1",
        receipt_version="v1",
        subject_id=subject.subject_id,
        subject_version=subject.subject_version,
        subject_content_hash=subject.content_hash,
        plan_id=subject.plan_id,
        plan_version=subject.plan_version,
        plan_content_hash=subject.plan_content_hash,
        account_id=subject.account_id,
        decision_snapshot_id=subject.decision_snapshot_id,
        requested_by=subject.requested_by,
        approved_by=_actor(12),
        issued_at=approved_at,
        valid_until=subject.valid_until,
    )
    ledger = DjangoTransitionPlanInactiveApprovalRepository()
    with ledger.atomic():
        ledger.append_subject(subject, recorded_at=approved_at)
        ledger.append(
            receipt,
            subject=subject,
            recorded_at=approved_at,
        )
    cutoff = timezone.now()
    runtime = build_django_transition_plan_owner_reader_runtime()

    plan_row = runtime.plan_order_reader.execute(
        GetExactActiveTransitionPlanOrderQuery(
            plan_id=plan.plan_id,
            plan_version=plan.version,
            order_ordinal=0,
            as_of=cutoff,
        )
    )
    receipt_row = runtime.inactive_receipt_reader.execute(
        GetExactInactiveTransitionPlanApprovalReceiptQuery(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=cutoff,
        )
    )

    assert plan_row.content_hash == subject.plan_content_hash
    assert plan_row.order_ordinal == 0
    assert receipt_row.content_hash == receipt.content_hash
    assert receipt_row.recorded_at == receipt.issued_at
    assert receipt_row.execution_permission == "inactive"
    assert receipt_row.must_not_execute is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("family", "risk_contract"),
    [
        (PORTFOLIO_PLAN_REVISION_FAMILY, {}),
        (PORTFOLIO_PLAN_REVISION_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: None}),
        (PORTFOLIO_PLAN_REVISION_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: {}}),
        (PORTFOLIO_PLAN_REVISION_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: "damaged"}),
        (CANONICAL_TRANSITION_PLAN_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: None}),
        (CANONICAL_TRANSITION_PLAN_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: {}}),
        (CANONICAL_TRANSITION_PLAN_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: "damaged"}),
        (CANONICAL_TRANSITION_PLAN_FAMILY, []),
    ],
)
def test_legacy_repository_and_owner_reads_reject_revision_family_or_marked_rows(
    family: str, risk_contract: object
) -> None:
    row = _revision_family_row(family=family, risk_contract=risk_contract)
    repository = PortfolioTransitionPlanRepository()

    assert repository.get(row.plan_id) is None
    assert repository.get_by_idempotency_key(str(row.idempotency_key)) is None
    with pytest.raises(ValueError):
        repository.approve(row.plan_id, row.decision_snapshot_id)

    row.refresh_from_db()
    assert row.status == "DRAFT"
    assert row.approved_at is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("family", "risk_contract"),
    [
        (PORTFOLIO_PLAN_REVISION_FAMILY, {}),
        (PORTFOLIO_PLAN_REVISION_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: None}),
        (PORTFOLIO_PLAN_REVISION_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: {}}),
        (PORTFOLIO_PLAN_REVISION_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: "damaged"}),
        (CANONICAL_TRANSITION_PLAN_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: None}),
        (CANONICAL_TRANSITION_PLAN_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: {}}),
        (CANONICAL_TRANSITION_PLAN_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: "damaged"}),
        (CANONICAL_TRANSITION_PLAN_FAMILY, []),
    ],
)
def test_legacy_exact_approval_provider_rejects_revision_family_or_marked_rows(
    family: str, risk_contract: object
) -> None:
    row = _revision_family_row(family=family, risk_contract=risk_contract, status="APPROVED")

    value = DjangoExactTransitionPlanDefinitionProvider().get_exact(
        plan_id=row.plan_id,
        plan_version=row.plan_version,
        as_of=timezone.now(),
    )

    assert value is None


@pytest.mark.django_db(transaction=True)
def test_legacy_inactive_approval_cannot_register_subject_for_ash08_row() -> None:
    row = _revision_family_row(
        family=PORTFOLIO_PLAN_REVISION_FAMILY,
        risk_contract={PORTFOLIO_PLAN_REVISION_MARKER: None},
        status="APPROVED",
    )
    repository = DjangoTransitionPlanInactiveApprovalRepository()
    workflow = RegisterTransitionPlanInactiveApprovalSubject(
        plan_provider=DjangoExactTransitionPlanDefinitionProvider(),
        repository=repository,
        actor=_actor(101),
    )

    with pytest.raises(TransitionPlanInactiveApprovalUnavailable):
        workflow.execute(
            RegisterTransitionPlanInactiveApprovalSubjectCommand(
                subject_id="ash08-compat-subject",
                subject_version="v1",
                plan_id=row.plan_id,
                plan_version=row.plan_version,
            )
        )

    assert TransitionPlanInactiveApprovalSubjectModel._default_manager.count() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("family", "risk_contract"),
    [
        (PORTFOLIO_PLAN_REVISION_FAMILY, {}),
        (CANONICAL_TRANSITION_PLAN_FAMILY, {PORTFOLIO_PLAN_REVISION_MARKER: "damaged"}),
    ],
)
def test_legacy_http_detail_and_approve_return_json_404_without_mutation(
    family: str, risk_contract: object
) -> None:
    row = _revision_family_row(family=family, risk_contract=risk_contract)
    user = get_user_model().objects.create_user(
        username=f"ash08-compat-http-{family}-{row.pk}", password="test-only"
    )
    client = Client()
    client.force_login(user)
    plan_url = f"/api/portfolio/transition-plans/{row.plan_id}/"

    collection = client.get("/api/portfolio/transition-plans/")
    detail = client.get(plan_url)
    approve = client.post(
        f"{plan_url}approve/",
        data={"decision_snapshot_id": row.decision_snapshot_id},
        content_type="application/json",
    )

    assert collection.status_code == 405
    assert collection["Content-Type"].startswith("application/json")
    assert detail.status_code == 404
    assert detail["Content-Type"].startswith("application/json")
    assert approve.status_code == 404
    assert approve["Content-Type"].startswith("application/json")
    row.refresh_from_db()
    assert row.status == "DRAFT"
    assert row.approved_at is None


@pytest.mark.django_db(transaction=True)
def test_valid_marked_projection_stays_out_of_legacy_readers() -> None:
    prepared_at = timezone.now()
    user = get_user_model().objects.create_user(
        username=f"ash08-valid-marked-owner-{uuid4().hex[:12]}", password="test-only"
    )
    account = SimulatedAccountModel._default_manager.create(
        user=user,
        account_name=f"ASH08 valid marked owner {uuid4().hex[:12]}",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
    )
    context = cast(
        _QualifiedCallerContext,
        SimpleNamespace(account=account, owner_id=user.pk),
    )
    revision = _build_revision(
        context=context,
        position_quantity=Decimal("300"),
        prepared_at=prepared_at,
    )
    revision_repository = DjangoTransitionPlanRevisionRepository(using="default")
    row_values = revision_repository._model_values(
        revision,
        idempotency_key=revision.plan.idempotency_key,
    )
    row_values["plan_contract_family"] = CANONICAL_TRANSITION_PLAN_FAMILY
    row = PortfolioTransitionPlanModel._default_manager.create(**row_values)

    assert row.immutable_payload_hash == transition_plan_content_hash_v1(revision.plan)
    wrapper = row.risk_contract[PORTFOLIO_PLAN_REVISION_MARKER]
    assert wrapper["revision"]["identity"]["revision_hash"] == revision.identity.revision_hash

    legacy_repository = PortfolioTransitionPlanRepository()
    assert legacy_repository.get(row.plan_id) is None
    assert legacy_repository.get_by_idempotency_key(str(row.idempotency_key)) is None
    decoded = revision_repository.get_exact(
        plan_id=row.plan_id,
        version=row.plan_version,
        expected_revision_hash=revision.identity.revision_hash,
        as_of=timezone.now(),
    )
    assert decoded is not None
    assert decoded.identity.revision_hash == revision.identity.revision_hash

    with pytest.raises(ValueError, match="immutable revision plan"):
        legacy_repository.approve(row.plan_id, row.decision_snapshot_id)
    row.refresh_from_db()
    assert row.status == "DRAFT"
    assert row.approved_at is None

    client = Client()
    client.force_login(user)
    response = client.get(f"/api/portfolio/transition-plans/{row.plan_id}/")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/json")

    row.status = "APPROVED"
    row.approved_at = timezone.now()
    row.save(update_fields=["status", "approved_at", "updated_at"])
    cutoff = timezone.now()
    assert (
        DjangoExactTransitionPlanDefinitionProvider().get_exact(
            plan_id=row.plan_id,
            plan_version=row.plan_version,
            as_of=cutoff,
        )
        is None
    )
    approved_revision = revision_repository.get_exact(
        plan_id=row.plan_id,
        version=row.plan_version,
        expected_revision_hash=revision.identity.revision_hash,
        as_of=cutoff,
    )
    assert approved_revision is not None
    assert approved_revision.identity.revision_hash == revision.identity.revision_hash
    assert approved_revision.plan.status == "APPROVED"


@pytest.mark.django_db(transaction=True)
def test_decision_workspace_legacy_reader_skips_new_rows_and_preserves_older_legacy_plan() -> None:
    legacy = _legacy_plan_row(plan_id="ash08-existing-legacy-plan")
    marked_legacy = _legacy_plan_row(
        plan_id="ash08-marked-legacy-plan",
        risk_contract={PORTFOLIO_PLAN_REVISION_MARKER: {"damaged": True}},
    )
    revision = _revision_family_row(
        family=PORTFOLIO_PLAN_REVISION_FAMILY,
        risk_contract={},
    )
    repository = LegacyPortfolioTransitionPlanRepository()

    assert repository.get_by_id(legacy.plan_id) is not None
    assert repository.get_by_id(marked_legacy.plan_id) is None
    assert repository.get_by_id(revision.plan_id) is None
    latest = repository.get_latest_for_account("7")
    assert latest is not None
    assert latest.plan_id == legacy.plan_id

    user = get_user_model().objects.create_user(
        username=f"ash08-workspace-http-{revision.pk}", password="test-only"
    )
    client = Client()
    client.force_login(user)
    plan_url = f"/api/decision/workspace/plans/{revision.plan_id}/"
    detail = client.get(plan_url)
    update = client.post(
        f"{plan_url}update/",
        data={},
        content_type="application/json",
    )
    assert detail.status_code == 404
    assert detail["Content-Type"].startswith("application/json")
    assert update.status_code == 404
    assert update["Content-Type"].startswith("application/json")
    revision.refresh_from_db()
    assert revision.status == "DRAFT"
    assert revision.approved_at is None
