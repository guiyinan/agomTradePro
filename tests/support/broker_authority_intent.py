"""Persist a canonical plan, its approval and a matching proposed Broker order for rehearsal."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.account.infrastructure.account_identity_snapshot_repository import (
    DjangoAccountIdentitySnapshotRepository,
)
from apps.broker_execution.ash09_checkpoint_composition import resolve_current_intent
from apps.broker_execution.domain.broker_account_identity_snapshot import AccountIdentitySourceRef
from apps.broker_execution.domain.order_approval_artifact import (
    BrokerOrderApprovalActor,
    BrokerOrderApprovalArtifact,
)
from apps.broker_execution.domain.rules import build_approval_digest
from apps.broker_execution.infrastructure.broker_account_identity_snapshot_repository import (
    DjangoBrokerAccountIdentitySnapshotRepository,
)
from apps.broker_execution.infrastructure.order_approval_artifact_repository import (
    DjangoBrokerOrderApprovalArtifactRepository,
)
from apps.broker_execution.infrastructure.plan_order_binding_repository import (
    DjangoBrokerPlanOrderBindingRepository,
)
from apps.broker_execution.infrastructure.portfolio_broker_account_binding_repository import (
    DjangoBrokerPortfolioAccountBindingRepository,
)
from apps.broker_execution.infrastructure.pre_risk_execution_scope_repository import (
    DjangoBrokerPreRiskExecutionScopeRepository,
)
from apps.portfolio.application.transition_plan_inactive_approval import (
    ApproveTransitionPlanInactive,
    ApproveTransitionPlanInactiveCommand,
    RegisterTransitionPlanInactiveApprovalSubject,
    RegisterTransitionPlanInactiveApprovalSubjectCommand,
)
from apps.portfolio.application.transition_plan_order_reader import (
    GetExactActiveTransitionPlanOrderQuery,
)
from apps.portfolio.infrastructure.repositories import PortfolioTransitionPlanRepository
from apps.portfolio.infrastructure.transition_plan_definition_provider import (
    DjangoExactTransitionPlanDefinitionProvider,
)
from apps.portfolio.infrastructure.transition_plan_inactive_approval_repository import (
    DjangoTransitionPlanInactiveApprovalRepository,
)
from apps.portfolio.transition_plan_owner_readers_composition import (
    build_django_transition_plan_owner_reader_runtime,
)
from tests.component.broker_execution import (
    test_broker_account_identity_snapshot_repository as broker_account,
)
from tests.component.broker_execution import test_order_approval_artifact_repository as orders
from tests.component.broker_execution import test_plan_order_binding_repository as plans
from tests.component.broker_execution import test_pre_risk_execution_scope_repository as scopes
from tests.component.broker_execution.test_portfolio_broker_account_binding_repository import (
    _binding as namespace_binding,
)
from tests.component.portfolio.test_transition_plan_owner_reader_adapters import _actor, _plan


@transaction.atomic
def bind_broker_to_live_portfolio_owner(*, identity, binding, using="default"):
    """Bind the physical Broker account to the Account source actually used by the Portfolio approval."""
    from apps.broker_execution.infrastructure.broker_order_scope_seal import BrokerReferenceDigester

    now = timezone.now()
    uid = identity.owner_user_id
    assert (
        binding.account_id == identity.physical_row_pk
        and binding.user_id == uid
        and binding.agent.user_id == uid
    )
    record = DjangoAccountIdentitySnapshotRepository(using=using).get_current_head(
        account_namespace=identity.account_namespace, account_id=identity.account_id, as_of=now
    )
    assert record is not None
    account = record.snapshot
    assert (account.source_id, account.source_version, account.content_hash) == (
        identity.source_id,
        identity.source_version,
        identity.identity_hash,
    )
    source = AccountIdentitySourceRef(
        account.source_id,
        account.source_version,
        account.content_hash,
        account.account_namespace,
        account.account_id,
        uid,
        account.account_type,
        account.is_active,
        account.recorded_at,
        account.valid_until,
    )
    end = min(now + timedelta(hours=1), identity.valid_until, account.valid_until)
    broker = broker_account._snapshot(
        snapshot_id=uuid4().hex,
        broker_account_namespace="qmt-live",
        broker_account_id=binding.account_id,
        owner_user_id=uid,
        binding_owner_user_id=uid,
        agent_owner_user_id=uid,
        agent_id=binding.agent.agent_id,
        broker_account_category=binding.account_type,
        account_source_ref=source,
        qmt_account_ref_digest=BrokerReferenceDigester().digest(
            opaque_reference=binding.broker_account_ref.encode()
        ),
        issued_at=now,
        recorded_at=now,
        valid_until=end,
        ttl_valid_until=end,
    )
    repository = DjangoBrokerAccountIdentitySnapshotRepository(using=using)
    with repository.atomic():
        repository.append(
            broker_account._record(
                broker, broker_account._actor(actor_id=f"user:{uid}", user_id=uid)
            ),
            expected_predecessor_hash=None,
            recorded_at=now,
        )
    mapping = namespace_binding(
        binding_id=uuid4().hex,
        broker_account_namespace=broker.broker_account_namespace,
        broker_account_id=broker.broker_account_id,
        portfolio_account_namespace=account.account_namespace,
        portfolio_account_id=account.account_id,
        owner_user_id=uid,
        broker_source_id=broker.snapshot_id,
        broker_source_version=broker.snapshot_version,
        broker_source_content_hash=broker.content_hash,
        portfolio_source_id=account.source_id,
        portfolio_source_version=account.source_version,
        portfolio_source_content_hash=account.content_hash,
        issued_at=now,
        recorded_at=now,
        valid_until=end,
    )
    links = DjangoBrokerPortfolioAccountBindingRepository(using=using)
    with links.atomic():
        return links.append(mapping, expected_predecessor_hash=None, recorded_at=now)


@transaction.atomic
def persist_signed_intent(
    *, account_binding, approver_user_id, agent_id, risk_policy_version, using="default"
):
    """Use an already issued real Broker/Portfolio namespace binding and two real test users."""
    order_id = uuid4()
    key = order_id.hex
    owner_id = account_binding.owner_user_id
    expiry = min(timezone.now() + timedelta(hours=1), account_binding.valid_until)
    base = _plan()
    plan = replace(
        base,
        plan_id=key,
        idempotency_key=key,
        expires_at=expiry,
        status="DRAFT",
        account_id=account_binding.portfolio_account_id,
        cash_before=Decimal("10000.00"),
        cash_after=Decimal("8974.00"),
        orders=(replace(base.orders[0], quantity=100, reference_price=Decimal("10.2500")),),
    )
    portfolio = PortfolioTransitionPlanRepository()
    portfolio.save(plan)
    portfolio.approve(plan.plan_id, plan.decision_snapshot_id)
    reader = DjangoExactTransitionPlanDefinitionProvider(using=using)
    ledger = DjangoTransitionPlanInactiveApprovalRepository(using=using)
    subject = RegisterTransitionPlanInactiveApprovalSubject(
        plan_provider=reader, repository=ledger, actor=_actor(owner_id)
    ).execute(
        RegisterTransitionPlanInactiveApprovalSubjectCommand(key, "v1", plan.plan_id, plan.version)
    )
    receipt = ApproveTransitionPlanInactive(
        plan_provider=reader, repository=ledger, actor=_actor(approver_user_id)
    ).execute(ApproveTransitionPlanInactiveCommand(key, "v1", key, "v1"))
    now = timezone.now()
    row = build_django_transition_plan_owner_reader_runtime(using=using).plan_order_reader.execute(
        GetExactActiveTransitionPlanOrderQuery(plan.plan_id, plan.version, 0, now)
    )
    snap = replace(
        orders._snapshot(),
        agent_id=agent_id,
        account_id=account_binding.broker_account_id,
        expires_at=expiry.isoformat(),
        estimated_amount=Decimal("1025.00"),
        risk_policy_version=risk_policy_version,
    )
    order = BrokerOrderApprovalArtifact(
        artifact_id=str(order_id),
        client_order_id=str(order_id),
        order_version=1,
        artifact_version="broker-live-order-approval-artifact.v1.1",
        account_id=snap.account_id,
        approval_snapshot=snap,
        approval_digest=build_approval_digest(snap),
        approved_by=BrokerOrderApprovalActor(
            actor_id=f"user:{approver_user_id}", user_id=approver_user_id, role="broker_approver"
        ),
        approved_at=now,
        valid_until=expiry,
    )
    order_repo = DjangoBrokerOrderApprovalArtifactRepository(using=using)
    with order_repo.atomic():
        order_repo.append(order, recorded_at=now)
    shared = {
        "portfolio_receipt_id": receipt.receipt_id,
        "portfolio_receipt_version": receipt.receipt_version,
        "portfolio_receipt_content_hash": receipt.content_hash,
        "portfolio_receipt_valid_until": receipt.valid_until,
        "portfolio_subject_id": subject.subject_id,
        "portfolio_subject_version": subject.subject_version,
        "portfolio_subject_content_hash": subject.content_hash,
        "broker_account_id": snap.account_id,
        "portfolio_account_id": plan.account_id,
        "order_artifact_id": str(order_id),
        "order_artifact_content_hash": order.content_hash,
        "order_artifact_identity_hash": order.identity_hash,
        "order_artifact_version": order.artifact_version,
        "order_version": 1,
        "order_approval_digest": order.approval_digest,
        "recorded_at": now,
        "valid_until": expiry,
    }
    binding = plans._binding(
        binding_id=key,
        portfolio_plan_id=plan.plan_id,
        portfolio_plan_version=plan.version,
        portfolio_plan_content_hash=row.content_hash,
        portfolio_plan_valid_until=row.valid_until,
        order_artifact_valid_until=expiry,
        plan_order_payload_json=row.order_payload_json,
        **shared,
    )
    bind_repo = DjangoBrokerPlanOrderBindingRepository(using=using)
    with bind_repo.atomic():
        bind_repo.append(binding, recorded_at=now, expected_predecessor_hash=None)
    pre_risk = scopes._scope(
        scope_id=key,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_content_hash=row.content_hash,
        plan_valid_until=row.valid_until,
        order_valid_until=expiry,
        order_risk_policy_version=risk_policy_version,
        **shared,
    )
    pre_repo = DjangoBrokerPreRiskExecutionScopeRepository(using=using)
    with pre_repo.atomic():
        pre_repo.append(pre_risk, recorded_at=now, expected_predecessor_hash=None)
    return resolve_current_intent(client_order_id=order_id, using=using, account_id=snap.account_id)
