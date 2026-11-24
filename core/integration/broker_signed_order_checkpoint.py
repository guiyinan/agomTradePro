"""Join current Portfolio and Risk authority to an owner-signed Broker order."""

from django.utils import timezone

from apps.broker_execution.application.checkpoint_authority import BrokerCheckpointIntent
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionPermissionError,
)
from apps.broker_execution.order_checkpoint_composition import VerifiedOrderCheckpoint


def read_signed_checkpoint(
    *, intent: BrokerCheckpointIntent, using: str
) -> VerifiedOrderCheckpoint:
    """Verify the exact signed order, current policy and account balances under the caller's locks."""
    from apps.broker_execution.order_execution_scope_composition import (
        read_current_order_execution_scope,
    )
    from apps.portfolio.transition_plan_checkpoint_composition import read_locked_transition_order
    from core.integration.broker_order_risk_authority import (
        read_current_signed_order_risk,
        require_signed_account_risk,
    )

    client_order_id = intent.client_order_id
    account_id = intent.snapshot.account_id
    owner_user_id = intent.owner_user_id
    plan = intent.sources.plan
    as_of = timezone.now()
    try:
        row, receipt = read_locked_transition_order(
            plan_id=intent.plan_id,
            plan_version=intent.plan_version,
            ordinal=intent.plan_order_ordinal,
            receipt_id=plan.portfolio_receipt_id,
            receipt_version=plan.portfolio_receipt_version,
            using=using,
            as_of=as_of,
        )
        grant = read_current_order_execution_scope(
            client_order_id=client_order_id,
            account_id=account_id,
            owner_user_id=owner_user_id,
            using=using,
        )
        risk = read_current_signed_order_risk(
            account_id=account_id,
            client_order_id=client_order_id,
            owner_user_id=owner_user_id,
            using=using,
        )
    except (BrokerExecutionPermissionError, ValueError) as error:
        raise BrokerExecutionConflictError("broker_checkpoint_sources_unavailable") from error
    if (row.content_hash, row.account_id, row.order_content_hash, row.valid_until) != (
        plan.portfolio_plan_content_hash,
        plan.portfolio_account_id,
        plan.plan_order_content_hash,
        plan.portfolio_plan_valid_until,
    ) or (
        receipt.plan_id,
        receipt.plan_version,
        receipt.plan_content_hash,
        receipt.account_id,
        receipt.subject_id,
        receipt.subject_version,
        receipt.subject_content_hash,
        receipt.content_hash,
        receipt.valid_until,
    ) != (
        intent.plan_id,
        intent.plan_version,
        row.content_hash,
        row.account_id,
        plan.portfolio_subject_id,
        plan.portfolio_subject_version,
        plan.portfolio_subject_content_hash,
        plan.portfolio_receipt_content_hash,
        plan.portfolio_receipt_valid_until,
    ):
        raise BrokerExecutionConflictError("broker_checkpoint_portfolio_scope_mismatch")
    if grant is None or risk is None:
        raise BrokerExecutionConflictError("broker_checkpoint_current_approval_missing")
    sealed = risk.authorization.subject.scope
    if (
        (
            sealed.execution_scope_id,
            sealed.execution_scope_version,
            sealed.execution_scope_hash,
            sealed.execution_scope_valid_until,
            sealed.account_id,
        )
        != (
            grant.execution_scope_id,
            grant.execution_scope_version,
            grant.execution_scope_hash,
            grant.valid_until,
            grant.account_id,
        )
        or (
            sealed.plan_id,
            sealed.plan_version,
            sealed.plan_content_hash,
            sealed.plan_approval_hash,
            sealed.plan_valid_until,
        )
        != (
            intent.plan_id,
            str(intent.plan_version),
            row.content_hash,
            receipt.content_hash,
            row.valid_until,
        )
        or (
            sealed.order_id,
            sealed.order_version,
            sealed.order_content_hash,
            sealed.order_valid_until,
            sealed.policy_version,
        )
        != (
            str(client_order_id),
            intent.sources.order.artifact_version,
            intent.sources.order.content_hash,
            intent.sources.order.valid_until,
            intent.snapshot.risk_policy_version,
        )
    ):
        raise BrokerExecutionConflictError("broker_checkpoint_risk_scope_mismatch")

    if intent.snapshot.limit_price is None:
        raise BrokerExecutionConflictError("broker_checkpoint_signed_limit_required")
    balances = require_signed_account_risk(
        plan_binding=intent.sources.plan,
        client_order_id=client_order_id,
        user_id=owner_user_id,
        account_id=account_id,
        asset_code=intent.snapshot.asset_code,
        side=intent.snapshot.side.value,
        quantity=intent.snapshot.quantity,
        limit_price=intent.snapshot.limit_price,
        using=using,
    )
    result = VerifiedOrderCheckpoint(
        intent,
        grant.execution_scope_hash,
        risk.authorization.content_hash,
        min(
            balances.valid_until,
            risk.authorization.valid_until,
            grant.valid_until,
            plan.valid_until,
            intent.sources.pre_risk.valid_until,
            intent.sources.account.valid_until,
        ),
        execution_scope_id=grant.execution_scope_id,
        execution_scope_version=grant.execution_scope_version,
        risk_approval_id=risk.authorization.authorization_id,
        risk_approval_version=risk.authorization.authorization_version,
    )
    result.require_unexpired(timezone.now())
    return result
