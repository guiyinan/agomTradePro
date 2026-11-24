"""Compose the Risk-owned two-person workflow with an exact Broker scope reader."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.risk_center.application.broker_order_execution_policy import (
    ActivateBrokerOrderExecutionPolicy,
    ActivateBrokerOrderExecutionPolicyCommand,
    BrokerOrderExecutionPolicyActivation,
    BrokerOrderExecutionPolicyActor,
    BrokerOrderExecutionPolicyUnavailable,
    ExactCurrentBrokerOrderRiskPolicyProvider,
)
from apps.risk_center.application.broker_order_risk_authorization import (
    ApproveBrokerOrderRiskAuthorization,
    ExactActiveBrokerOrderExecutionScopeProvider,
    RegisterBrokerOrderRiskAuthorizationSubject,
)
from apps.risk_center.domain.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationActor,
)
from apps.risk_center.infrastructure.broker_order_execution_policy_repository import (
    DjangoBrokerOrderExecutionPolicyRepository,
)
from apps.risk_center.infrastructure.broker_order_risk_authorization_repository import (
    DjangoBrokerOrderRiskAuthorizationRepository,
)
from apps.risk_center.infrastructure.broker_policy_sources import (
    LiveBrokerPolicySources,
    lock_risk_configuration,
)


@dataclass(frozen=True, slots=True)
class OrderRiskIssuance:
    """Register an exact subject or independently approve it using current Risk policy."""

    register: RegisterBrokerOrderRiskAuthorizationSubject
    approve: ApproveBrokerOrderRiskAuthorization


def build_order_risk_issuance(
    *,
    scope_provider: ExactActiveBrokerOrderExecutionScopeProvider,
    actor: BrokerOrderRiskAuthorizationActor,
    using: str,
) -> OrderRiskIssuance:
    """Use the same database alias for all Risk reads and the signed ledger append."""
    repository = DjangoBrokerOrderRiskAuthorizationRepository(using=using)
    policy = ExactCurrentBrokerOrderRiskPolicyProvider(
        DjangoBrokerOrderExecutionPolicyRepository(using=using)
    )
    return OrderRiskIssuance(
        RegisterBrokerOrderRiskAuthorizationSubject(
            scope_provider=scope_provider,
            policy_provider=policy,
            actor=actor,
            repository=repository,
        ),
        ApproveBrokerOrderRiskAuthorization(
            scope_provider=scope_provider,
            policy_provider=policy,
            subject_provider=repository,
            actor=actor,
            repository=repository,
        ),
    )


def require_current_account_policy(
    *, account_id: int, as_of: datetime, using: str
) -> BrokerOrderExecutionPolicyActivation:
    """Compare the immutable activation to the locked live Risk controls and all five sources."""
    activation = DjangoBrokerOrderExecutionPolicyRepository(using=using).get_current_head(
        account_id=account_id, as_of=as_of
    )
    if activation is None or not activation.policy.is_active_at(as_of):
        raise BrokerOrderExecutionPolicyUnavailable("broker_risk_policy_missing")
    policy = activation.policy
    provider = LiveBrokerPolicySources(
        account_id, policy.policy_id, policy.policy_version, policy.valid_until, using
    )
    current = provider.get_exact_active(
        source_snapshot_id=policy.source_snapshot_id,
        source_snapshot_version=policy.source_snapshot_version,
        as_of=as_of,
    )
    if (
        current is None
        or current.content_hash != policy.source_snapshot_hash
        or current.controls != policy.controls
    ):
        raise BrokerOrderExecutionPolicyUnavailable("broker_risk_policy_source_changed")
    return activation


def activate_current_account_policy(
    *,
    account_id: int,
    policy_id: str,
    policy_version: str,
    valid_until: datetime,
    actor: BrokerOrderExecutionPolicyActor,
    using: str,
) -> BrokerOrderExecutionPolicyActivation:
    """Publish a staff-certified finite policy from the locked real configuration only."""
    source = LiveBrokerPolicySources(account_id, policy_id, policy_version, valid_until, using)
    return ActivateBrokerOrderExecutionPolicy(
        source_provider=source,
        actor=actor,
        repository=DjangoBrokerOrderExecutionPolicyRepository(using=using),
    ).execute(
        ActivateBrokerOrderExecutionPolicyCommand(
            policy_id, policy_version, source.source_id, policy_version
        )
    )


def fence_signed_pretrade_policy(*, using: str) -> None:
    """Hold the risk configuration stable until the caller's order transaction commits."""
    lock_risk_configuration(using=using)
