"""Resolve an inactive, pre-approved Broker intent from a stable order identity."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TypeVar
from uuid import UUID

from django.db import DatabaseError, OperationalError, connections, transaction
from django.utils import timezone

from apps.broker_execution.application.checkpoint_authority import (
    BrokerCheckpointIntent,
    BrokerCheckpointSources,
)
from apps.broker_execution.application.evidence_gate import BROKER_ORDER_EVIDENCE_BLOCKER
from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.domain.services import approval_digest_for_order
from apps.broker_execution.infrastructure.order_approval_artifact_models import (
    BrokerOrderApprovalArtifactModel,
)
from apps.broker_execution.infrastructure.order_approval_artifact_repository import (
    DjangoBrokerOrderApprovalArtifactRepository,
)
from apps.broker_execution.infrastructure.plan_order_binding_models import (
    BrokerPlanOrderBindingModel,
)
from apps.broker_execution.infrastructure.plan_order_binding_repository import (
    DjangoBrokerPlanOrderBindingRepository,
)
from apps.broker_execution.infrastructure.portfolio_broker_account_binding_models import (
    BrokerPortfolioAccountBindingModel,
)
from apps.broker_execution.infrastructure.portfolio_broker_account_binding_repository import (
    DjangoBrokerPortfolioAccountBindingRepository,
)
from apps.broker_execution.infrastructure.pre_risk_execution_scope_models import (
    BrokerPreRiskExecutionScopeModel,
)
from apps.broker_execution.infrastructure.pre_risk_execution_scope_repository import (
    DjangoBrokerPreRiskExecutionScopeRepository,
)
from apps.risk_center.application.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationUnavailable,
)
from apps.risk_center.broker_checkpoint_composition import read_current_broker_order_risk

_T = TypeVar("_T")


def _only(values: list[_T], name: str) -> _T:
    if len(values) != 1:
        raise BrokerExecutionConflictError(f"broker_checkpoint_{name}_missing_or_ambiguous")
    return values[0]


def resolve_current_intent(
    *, client_order_id: UUID, using: str, account_id: int | None = None
) -> BrokerCheckpointIntent:
    """Resolve the pre-existing plan, owner user and actual order economics at this read."""
    if type(client_order_id) is not UUID:
        raise ValueError("checkpoint requires a stable order UUID")
    db = connections[using]
    if not db.in_atomic_block:
        raise BrokerExecutionConflictError("broker_checkpoint_transaction_required")
    as_of = timezone.now()
    order_id = str(client_order_id)
    accounts = BrokerPreRiskExecutionScopeModel._default_manager.using(using).filter(
        order_artifact_id=client_order_id, recorded_at__lte=as_of
    )
    if account_id is not None:
        accounts = accounts.filter(broker_account_id=account_id)
    account_id = _only(
        list(accounts.order_by().values_list("broker_account_id", flat=True).distinct()[:2]),
        "pre_risk_scope",
    )
    pre_risk = DjangoBrokerPreRiskExecutionScopeRepository(using=using).get_current_head(
        broker_account_id=account_id, order_artifact_id=order_id, as_of=as_of
    )
    if pre_risk is None:
        raise BrokerExecutionConflictError("broker_checkpoint_pre_risk_missing")
    latest_version = (
        BrokerOrderApprovalArtifactModel._default_manager.using(using)
        .filter(client_order_id=client_order_id, recorded_at__lte=as_of)
        .order_by("-order_version")
        .values_list("order_version", flat=True)
        .first()
    )
    if latest_version != pre_risk.order_version:
        raise BrokerExecutionConflictError("broker_checkpoint_order_version_changed")
    order = DjangoBrokerOrderApprovalArtifactRepository(using=using).get_exact(
        artifact_id=order_id,
        artifact_version=pre_risk.order_artifact_version,
        expected_content_hash=pre_risk.order_artifact_content_hash,
        as_of=as_of,
    )
    if order is None:
        raise BrokerExecutionConflictError("broker_checkpoint_order_artifact_missing")
    plans = BrokerPlanOrderBindingModel._default_manager.using(using).filter(
        order_artifact_id=client_order_id,
        recorded_at__lte=as_of,
        portfolio_plan_id=pre_risk.plan_id,
        portfolio_plan_version=pre_risk.plan_version,
    )
    ordinal = _only(
        list(plans.order_by().values_list("plan_order_ordinal", flat=True).distinct()[:2]),
        "ordinal",
    )
    plan = DjangoBrokerPlanOrderBindingRepository(using=using).get_current_head(
        plan_id=pre_risk.plan_id,
        plan_version=pre_risk.plan_version,
        plan_order_ordinal=ordinal,
        order_artifact_id=order_id,
        as_of=as_of,
    )
    if plan is None:
        raise BrokerExecutionConflictError("broker_checkpoint_plan_binding_missing")
    namespaces = BrokerPortfolioAccountBindingModel._default_manager.using(using).filter(
        broker_account_id=account_id,
        recorded_at__lte=as_of,
    )
    namespace = _only(
        list(
            namespaces.order_by().values_list("broker_account_namespace", flat=True).distinct()[:2]
        ),
        "namespace",
    )
    account = DjangoBrokerPortfolioAccountBindingRepository(using=using).get_current_head(
        broker_account_namespace=namespace,
        broker_account_id=account_id,
        as_of=as_of,
    )
    if account is None:
        raise BrokerExecutionConflictError("broker_checkpoint_account_binding_missing")
    sources = BrokerCheckpointSources(order=order, plan=plan, account=account, pre_risk=pre_risk)
    intent = BrokerCheckpointIntent(
        client_order_id=client_order_id,
        order_version=order.order_version,
        plan_id=pre_risk.plan_id,
        plan_version=pre_risk.plan_version,
        plan_order_ordinal=ordinal,
        broker_account_namespace=namespace,
        owner_user_id=account.owner_user_id,
        snapshot=order.approval_snapshot,
        sources=sources,
    )
    sources.require_matches(intent, as_of)
    return intent


@contextmanager
def bounded_checkpoint_diagnostic(*, using: str) -> Iterator[None]:
    """Limit lock waits for this optional inspection and restore the caller's setting."""
    db = connections[using]
    with transaction.atomic(using=using):
        previous: str | None = None
        if db.vendor == "postgresql":
            with db.cursor() as cursor:
                cursor.execute(
                    "SELECT current_setting('lock_timeout'), setting::int "
                    "FROM pg_catalog.pg_settings WHERE name = 'lock_timeout'"
                )
                setting, milliseconds = cursor.fetchone()
                if milliseconds == 0 or milliseconds > 250:
                    previous = setting
                    cursor.execute("SELECT set_config('lock_timeout', '250ms', true)")
        yield
        if previous is not None:
            with db.cursor() as cursor:
                cursor.execute("SELECT set_config('lock_timeout', %s, true)", (previous,))


def inspect_checkpoint_blockers(
    *,
    user_id: int,
    client_order_id: UUID,
    account_id: int,
    order_payload: Mapping[str, object],
    using: str,
) -> tuple[str, ...]:
    """Explain the current owner's closed gate without exporting any artifact or hash."""
    if not connections[using].in_atomic_block:
        raise BrokerExecutionConflictError("broker_checkpoint_transaction_required")
    blockers = [
        BROKER_ORDER_EVIDENCE_BLOCKER,
        "broker_checkpoint_execution_scope_owner_not_integrated",
        "broker_checkpoint_benchmark_execution_authority_not_integrated",
        "broker_checkpoint_scoped_evidence_execution_authority_not_integrated",
    ]
    intent: BrokerCheckpointIntent | None = None
    try:
        with transaction.atomic(using=using):
            resolved = resolve_current_intent(
                client_order_id=client_order_id, account_id=account_id, using=using
            )
            digest = approval_digest_for_order(order_payload)
            if resolved.owner_user_id != user_id:
                blockers.append("broker_checkpoint_owner_binding_unavailable")
            elif digest != resolved.sources.order.approval_digest or digest != order_payload.get(
                "approval_digest"
            ):
                blockers.append("broker_checkpoint_order_content_mismatch")
            else:
                intent = resolved
    except BrokerExecutionConflictError as exc:
        # Only local resolver codes carry no source data. Never expose stored values.
        blockers.append(str(exc))
    except (ArithmeticError, DatabaseError, KeyError, TypeError, ValueError):
        blockers.append("broker_checkpoint_sources_unavailable")
    try:
        with transaction.atomic(using=using):
            risk = read_current_broker_order_risk(
                account_id=account_id, client_order_id=client_order_id, using=using
            )
    except BrokerOrderRiskAuthorizationUnavailable:
        blockers.append("broker_checkpoint_risk_fence_unavailable")
    except OperationalError:
        blockers.append("broker_checkpoint_risk_fence_unavailable")
    except (DatabaseError, TypeError, ValueError):
        blockers.append("broker_checkpoint_risk_sources_unavailable")
    else:
        if risk is None:
            blockers.append("broker_checkpoint_risk_approval_or_current_policy_unavailable")
        elif intent is not None:
            sealed = risk.authorization.subject.scope
            plan = intent.sources.plan
            if (
                sealed.plan_id,
                sealed.plan_version,
                sealed.plan_content_hash,
                sealed.plan_approval_hash,
                sealed.plan_valid_until,
            ) != (
                intent.plan_id,
                str(intent.plan_version),
                plan.portfolio_plan_content_hash,
                plan.portfolio_receipt_content_hash,
                plan.portfolio_plan_valid_until,
            ) or (
                sealed.order_id,
                sealed.order_version,
                sealed.order_content_hash,
                sealed.order_valid_until,
                sealed.policy_version,
            ) != (
                str(client_order_id),
                intent.sources.order.artifact_version,
                intent.sources.order.content_hash,
                intent.sources.order.valid_until,
                intent.snapshot.risk_policy_version,
            ):
                blockers.append("broker_checkpoint_risk_scope_mismatch")
    return tuple(blockers)
