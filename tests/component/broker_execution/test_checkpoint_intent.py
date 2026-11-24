"""The Broker pre-built intent is reconstructed only from four actual stored ledgers."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.ash09_checkpoint_composition import resolve_current_intent
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
from tests.component.broker_execution import test_order_approval_artifact_repository as orders
from tests.component.broker_execution import test_plan_order_binding_repository as plans
from tests.component.broker_execution import (
    test_portfolio_broker_account_binding_repository as accounts,
)
from tests.component.broker_execution import test_pre_risk_execution_scope_repository as scopes


@pytest.mark.django_db
def test_real_persisted_order_intent_and_later_artifact_supersession(monkeypatch):
    order = orders._artifact()
    stored_at = orders.RECORDED_AT
    cutoff = stored_at + timedelta(minutes=1)
    monkeypatch.setattr("django.utils.timezone.now", lambda: cutoff)
    ledger = DjangoBrokerOrderApprovalArtifactRepository()
    with ledger.atomic():
        ledger.append(order, recorded_at=stored_at)
    plan = plans._binding(
        order_artifact_identity_hash=order.identity_hash,
        order_artifact_content_hash=order.content_hash,
        order_approval_digest=order.approval_digest,
        recorded_at=stored_at,
        order_artifact_valid_until=order.valid_until,
        valid_until=order.valid_until,
    )
    plan_ledger = DjangoBrokerPlanOrderBindingRepository()
    with plan_ledger.atomic():
        plan_ledger.append(plan, recorded_at=stored_at, expected_predecessor_hash=None)
    account = accounts._binding(
        broker_account_id=order.account_id,
        portfolio_account_id=plan.portfolio_account_id,
        issued_at=stored_at,
        recorded_at=stored_at,
        valid_until=order.valid_until,
    )
    account_ledger = DjangoBrokerPortfolioAccountBindingRepository()
    with account_ledger.atomic():
        account_ledger.append(account, recorded_at=stored_at, expected_predecessor_hash=None)
    scope = scopes._scope(
        order_artifact_identity_hash=order.identity_hash,
        order_artifact_content_hash=order.content_hash,
        order_artifact_version=order.artifact_version,
        order_approval_digest=order.approval_digest,
        order_risk_policy_version=order.approval_snapshot.risk_policy_version,
        order_valid_until=order.valid_until,
        valid_until=order.valid_until,
        portfolio_receipt_valid_until=plan.portfolio_receipt_valid_until,
        plan_valid_until=plan.portfolio_plan_valid_until,
        recorded_at=stored_at,
    )
    scope_ledger = DjangoBrokerPreRiskExecutionScopeRepository()
    with scope_ledger.atomic():
        scope_ledger.append(scope, recorded_at=stored_at, expected_predecessor_hash=None)

    order_uuid = UUID(order.client_order_id)
    resolved = resolve_current_intent(client_order_id=order_uuid, using="default")
    assert resolved.snapshot == order.approval_snapshot
    assert resolved.owner_user_id == account.owner_user_id
    assert resolved.plan_id == plan.portfolio_plan_id
    assert resolved.order_version == order.order_version
    # A pending newer immutable order must invalidate the old pre-Risk binding.
    newer = replace(
        order,
        order_version=4,
        artifact_version=order.artifact_version[:-1] + "4",
        content_hash="",
        identity_hash="",
    )
    with ledger.atomic():
        ledger.append(newer, recorded_at=cutoff)
    with pytest.raises(BrokerExecutionConflictError, match="order_version_changed"):
        resolve_current_intent(client_order_id=order_uuid, using="default")


@pytest.mark.django_db
def test_unknown_order_cannot_acquire_a_checkpoint_intent():
    with pytest.raises(BrokerExecutionConflictError, match="pre_risk_scope_missing_or_ambiguous"):
        resolve_current_intent(client_order_id=uuid4(), using="default")
