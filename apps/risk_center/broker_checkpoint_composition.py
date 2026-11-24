"""Risk-owned current authorization and active policy under the caller's transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import connections

from apps.risk_center.application.broker_order_execution_policy import (
    ExactCurrentBrokerOrderRiskPolicyProvider,
)
from apps.risk_center.application.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationUnavailable,
    BrokerOrderRiskPolicyDefinition,
)
from apps.risk_center.domain.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationRecord,
)
from apps.risk_center.infrastructure.broker_order_execution_policy_repository import (
    DjangoBrokerOrderExecutionPolicyRepository,
)
from apps.risk_center.infrastructure.broker_order_risk_authorization_repository import (
    DjangoBrokerOrderRiskAuthorizationRepository,
)


@dataclass(frozen=True, slots=True)
class CurrentBrokerOrderRisk:
    """One scoped risk approval and the independently resolved active policy."""

    authorization: BrokerOrderRiskAuthorizationRecord
    policy: BrokerOrderRiskPolicyDefinition


@dataclass(frozen=True, slots=True)
class _CheckpointClock:
    as_of: datetime

    def now(self) -> datetime:
        return self.as_of


def read_current_broker_order_risk(
    *, account_id: int, client_order_id: UUID, using: str
) -> CurrentBrokerOrderRisk | None:
    """Hold replacement fences until the owning transaction ends and read both heads."""
    db = connections[using]
    if type(account_id) is not int or account_id < 1 or type(client_order_id) is not UUID:
        raise ValueError("invalid Risk checkpoint identity")
    if not db.in_atomic_block or db.vendor != "postgresql":
        raise BrokerOrderRiskAuthorizationUnavailable(
            "current risk checkpoint requires a PostgreSQL transaction"
        )
    with db.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        if cursor.fetchone() != ("read committed",):
            raise BrokerOrderRiskAuthorizationUnavailable(
                "current risk checkpoint requires read committed"
            )
        # AccessShare forbids concurrent truncation. Row triggers serialize replacements
        # on these two logical keys, including a first insertion where no row exists.
        cursor.execute("""
            LOCK TABLE risk_center_broker_execution_policy_source,
                       risk_center_broker_execution_policy_activation,
                       risk_center_broker_order_risk_subject,
                       risk_center_broker_order_risk_authorization IN ACCESS SHARE MODE
        """)
        cursor.execute("""
            SELECT count(*) FROM pg_catalog.pg_trigger
            WHERE tgname = 'risk_broker_checkpoint_fence' AND tgenabled = 'A'
              AND tgrelid IN ('risk_center_broker_execution_policy_source'::regclass,
                              'risk_center_broker_execution_policy_activation'::regclass,
                              'risk_center_broker_order_risk_subject'::regclass,
                              'risk_center_broker_order_risk_authorization'::regclass)
        """)
        if cursor.fetchone() != (4,):
            raise BrokerOrderRiskAuthorizationUnavailable("risk checkpoint fences are unavailable")
        for scope, order_id in (("policy", ""), ("authorization", str(client_order_id))):
            cursor.execute(
                "SELECT pg_advisory_xact_lock_shared(risk_broker_checkpoint_scope(%s, %s, %s))",
                (scope, account_id, order_id),
            )
        cursor.execute("SELECT clock_timestamp()")
        as_of: datetime = cursor.fetchone()[0]
    clock = _CheckpointClock(as_of)
    authorization = DjangoBrokerOrderRiskAuthorizationRepository(
        using=using, clock=clock
    ).get_current_head(account_id=account_id, order_id=str(client_order_id), as_of=as_of)
    if authorization is None or not authorization.is_valid_at(as_of):
        return None
    sealed = authorization.subject.scope
    policy = ExactCurrentBrokerOrderRiskPolicyProvider(
        DjangoBrokerOrderExecutionPolicyRepository(using=using, clock=clock)
    ).get_exact_active(
        policy_id=sealed.policy_id, policy_version=sealed.policy_version, as_of=as_of
    )
    if policy is None or (
        policy.account_id,
        policy.policy_content_hash,
        policy.policy_activation_hash,
        policy.valid_until,
    ) != (
        account_id,
        sealed.policy_content_hash,
        sealed.policy_activation_hash,
        sealed.policy_valid_until,
    ):
        return None
    return CurrentBrokerOrderRisk(authorization, policy)
