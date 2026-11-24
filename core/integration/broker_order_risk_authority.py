"""Wire order-specific human consent, live account balances and the Risk-owned issuer."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.utils import timezone
from rest_framework.request import Request

from apps.account.benchmark_actor_composition import read_order_risk_actor
from apps.account.live_account_owner_composition import locked_account_owner_session
from apps.broker_execution.application.checkpoint_authority import BrokerCheckpointIntent
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionPermissionError,
)
from apps.broker_execution.ash09_checkpoint_composition import resolve_current_intent
from apps.broker_execution.domain.plan_order_binding import BrokerPlanOrderBinding
from apps.broker_execution.signed_account_risk_composition import locked_signed_order_balances
from apps.risk_center.application.broker_order_execution_policy import (
    BrokerOrderExecutionPolicyActivation,
    BrokerOrderExecutionPolicyActor,
    BrokerOrderExecutionPolicyUnavailable,
)
from apps.risk_center.application.broker_order_risk_authorization import (
    ApproveBrokerOrderRiskAuthorizationCommand,
    BrokerOrderExecutionScopeDefinition,
    BrokerOrderRiskAuthorizationUnavailable,
    RegisterBrokerOrderRiskAuthorizationSubjectCommand,
)
from apps.risk_center.application.trade_guard import (
    EvaluatePreTradeRiskUseCase,
    PreTradeRiskCheckResult,
)
from apps.risk_center.broker_checkpoint_composition import (
    CurrentBrokerOrderRisk,
    lock_broker_risk_heads,
    read_current_broker_order_risk,
)
from apps.risk_center.broker_risk_issuance_composition import (
    activate_current_account_policy,
    build_order_risk_issuance,
    fence_signed_pretrade_policy,
    require_current_account_policy,
)
from apps.risk_center.domain.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationActor,
    BrokerOrderRiskAuthorizationActorKind,
    BrokerOrderRiskAuthorizationRecord,
    BrokerOrderRiskAuthorizationSubject,
)
from core.exceptions import AuthorizationError, BusinessLogicError
from shared.numeric import safe_float


@dataclass(frozen=True, slots=True)
class ActivateSignedOrderPolicy:
    """An explicit human validity limit on the independently resolved account policy."""

    policy_id: str
    policy_version: str
    valid_until: datetime


@dataclass(frozen=True, slots=True)
class SignedAccountRisk:
    """Pre-trade outcome tied to the original signed snapshot and execution quote deadline."""

    result: PreTradeRiskCheckResult
    valid_until: datetime
    snapshot_id: int
    source_hash: str
    captured_at: datetime


def _risk_value(value: Decimal) -> float:
    number = safe_float(value)
    if number is None or number < 0:
        raise BrokerExecutionConflictError("signed_account_risk_amount_invalid")
    return number


def require_signed_account_risk(
    *,
    client_order_id: UUID,
    plan_binding: BrokerPlanOrderBinding,
    user_id: int,
    account_id: int,
    asset_code: str,
    side: str,
    quantity: Decimal,
    limit_price: Decimal,
    using: str,
) -> SignedAccountRisk:
    """Apply Risk Center's pre-trade policy to a locked, still actionable signed QMT account."""
    source = locked_signed_order_balances(
        plan_binding=plan_binding,
        client_order_id=client_order_id,
        user_id=user_id,
        account_id=account_id,
        asset_code=asset_code,
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        using=using,
    )
    fence_signed_pretrade_policy(using=using)
    report = source.report
    result = EvaluatePreTradeRiskUseCase().execute(
        account_id=account_id,
        symbol=asset_code,
        side=side,
        quantity=_risk_value(quantity),
        price=_risk_value(limit_price),
        account_equity=_risk_value(report.total_asset),
        total_position_value=_risk_value(source.projected_position_value),
        cash_balance=_risk_value(source.cash_after_reservations),
        current_symbol_position_value=_risk_value(source.symbol_value),
    )
    if not result.passed or result.violations or timezone.now() >= source.valid_until:
        raise BrokerExecutionConflictError("signed_account_risk_policy_rejected")
    return SignedAccountRisk(
        result, source.valid_until, report.snapshot_id, report.content_hash, report.captured_at
    )


@dataclass(frozen=True, slots=True)
class _SignedScope:
    intent: BrokerCheckpointIntent
    using: str

    def current(self, as_of: datetime) -> BrokerOrderExecutionScopeDefinition | None:
        """Revalidate the specific order permission and all immutable Broker bindings."""
        from apps.broker_execution.order_execution_scope_composition import (
            read_current_order_execution_scope,
        )

        order = self.intent
        grant = read_current_order_execution_scope(
            client_order_id=order.client_order_id,
            account_id=order.snapshot.account_id,
            owner_user_id=order.owner_user_id,
            using=self.using,
        )
        if (
            grant is None
            or (
                grant.client_order_id,
                grant.account_id,
                grant.owner_user_id,
                grant.order_version,
                grant.order_content_hash,
                grant.plan_binding_hash,
                grant.pre_risk_hash,
            )
            != (
                order.client_order_id,
                order.snapshot.account_id,
                order.owner_user_id,
                order.order_version,
                order.sources.order.content_hash,
                order.sources.plan.content_hash,
                order.sources.pre_risk.content_hash,
            )
            or not grant.recorded_at <= as_of < grant.valid_until
        ):
            return None
        plan, artifact = order.sources.plan, order.sources.order
        return BrokerOrderExecutionScopeDefinition(
            grant.execution_scope_id,
            grant.execution_scope_version,
            grant.execution_scope_hash,
            grant.account_id,
            order.plan_id,
            str(order.plan_version),
            plan.portfolio_plan_content_hash,
            plan.portfolio_receipt_content_hash,
            plan.portfolio_plan_valid_until,
            str(order.client_order_id),
            artifact.artifact_version,
            artifact.content_hash,
            artifact.valid_until,
            grant.valid_until,
            grant.recorded_at,
        )

    def get_exact_active(
        self, *, execution_scope_id: str, execution_scope_version: str, as_of: datetime
    ) -> BrokerOrderExecutionScopeDefinition | None:
        """Select only the registered exact version of this operator scope."""
        scope = self.current(as_of)
        if scope is None or (scope.execution_scope_id, scope.execution_scope_version) != (
            execution_scope_id,
            execution_scope_version,
        ):
            return None
        return scope


def _authorized_actor(*, user_id: int | None, owner_user_id: int, using: str) -> None:
    if (
        user_id is None
        or read_order_risk_actor(user_id=user_id, owner_user_id=owner_user_id, using=using) is None
    ):
        raise BrokerExecutionPermissionError("broker_checkpoint_risk_approver_unavailable")


def read_current_signed_order_risk(
    *, account_id: int, client_order_id: UUID, owner_user_id: int, using: str
) -> CurrentBrokerOrderRisk | None:
    """Verify approved configuration, current staff and exact policy at a Broker checkpoint."""
    current = read_current_broker_order_risk(
        account_id=account_id, client_order_id=client_order_id, using=using
    )
    if current is None:
        return None
    activation = require_current_account_policy(
        account_id=account_id, as_of=timezone.now(), using=using
    )
    if activation.content_hash != current.policy.policy_activation_hash:
        return None
    auth = current.authorization
    for signer in (
        activation.activated_by.user_id,
        auth.subject.requested_by.user_id,
        auth.approved_by.user_id,
    ):
        _authorized_actor(user_id=signer, owner_user_id=owner_user_id, using=using)
    return current


def issue_order_risk_decision(
    *,
    request: Request,
    client_order_id: UUID,
    account_id: int,
    command: (
        ActivateSignedOrderPolicy
        | RegisterBrokerOrderRiskAuthorizationSubjectCommand
        | ApproveBrokerOrderRiskAuthorizationCommand
    ),
    using: str = "default",
) -> (
    BrokerOrderExecutionPolicyActivation
    | BrokerOrderRiskAuthorizationSubject
    | BrokerOrderRiskAuthorizationRecord
):
    """Activate current controls, request Risk review or independently sign one exact order."""
    deadlines: list[datetime] = []

    def require_fresh() -> None:
        if not deadlines or timezone.now() >= min(deadlines):
            raise BrokerOrderRiskAuthorizationUnavailable("broker_risk_issuance_expired")

    with locked_account_owner_session(
        request=request, using=using, before_commit=require_fresh
    ) as user:
        intent = resolve_current_intent(
            client_order_id=client_order_id, account_id=account_id, using=using
        )
        _authorized_actor(user_id=user.pk, owner_user_id=intent.owner_user_id, using=using)
        scopes = _SignedScope(intent, using)
        scope = scopes.current(timezone.now())
        if scope is None:
            raise BrokerOrderRiskAuthorizationUnavailable("broker_risk_order_scope_unavailable")
        deadlines.append(scope.scope_valid_until)
        lock_broker_risk_heads(
            account_id=account_id,
            client_order_id=client_order_id,
            using=using,
            write_policy=isinstance(command, ActivateSignedOrderPolicy),
            write_authorization=not isinstance(command, ActivateSignedOrderPolicy),
        )
        actor_id = f"user:{user.pk}"
        if isinstance(command, ActivateSignedOrderPolicy):
            if (
                command.policy_version != intent.snapshot.risk_policy_version
                or command.valid_until.utcoffset() is None
                or not timezone.now() < command.valid_until <= scope.scope_valid_until
            ):
                raise BrokerOrderExecutionPolicyUnavailable("broker_risk_policy_scope_mismatch")
            deadlines.append(command.valid_until)
            return activate_current_account_policy(
                account_id=account_id,
                policy_id=command.policy_id,
                policy_version=command.policy_version,
                valid_until=command.valid_until,
                actor=BrokerOrderExecutionPolicyActor(actor_id, user.pk),
                using=using,
            )
        activation = require_current_account_policy(
            account_id=account_id, as_of=timezone.now(), using=using
        )
        _authorized_actor(
            user_id=activation.activated_by.user_id, owner_user_id=intent.owner_user_id, using=using
        )
        policy = activation.policy
        if policy.policy_version != intent.snapshot.risk_policy_version or (
            isinstance(command, RegisterBrokerOrderRiskAuthorizationSubjectCommand)
            and (command.policy_id, command.policy_version)
            != (policy.policy_id, policy.policy_version)
        ):
            raise BrokerOrderRiskAuthorizationUnavailable("broker_risk_order_policy_mismatch")
        order = intent.snapshot
        if order.limit_price is None:
            raise BrokerOrderRiskAuthorizationUnavailable("broker_risk_order_price_unavailable")
        risk = require_signed_account_risk(
            plan_binding=intent.sources.plan,
            client_order_id=client_order_id,
            user_id=intent.owner_user_id,
            account_id=account_id,
            asset_code=order.asset_code,
            side=order.side.value,
            quantity=order.quantity,
            limit_price=order.limit_price,
            using=using,
        )
        deadlines.extend((risk.valid_until, policy.valid_until))
        actor = BrokerOrderRiskAuthorizationActor(
            actor_id, BrokerOrderRiskAuthorizationActorKind.HUMAN, True, user.pk
        )
        issuance = build_order_risk_issuance(scope_provider=scopes, actor=actor, using=using)
        if isinstance(command, RegisterBrokerOrderRiskAuthorizationSubjectCommand):
            subject = issuance.register.execute(command)
            deadlines.append(subject.valid_until)
            return subject
        approval = issuance.approve.execute(command)
        _authorized_actor(
            user_id=approval.subject.requested_by.user_id,
            owner_user_id=intent.owner_user_id,
            using=using,
        )
        deadlines.append(approval.valid_until)
        return approval


def issue_order_risk_from_request(
    *,
    request: Request,
    client_order_id: UUID,
    account_id: int,
    command: (
        ActivateSignedOrderPolicy
        | RegisterBrokerOrderRiskAuthorizationSubjectCommand
        | ApproveBrokerOrderRiskAuthorizationCommand
    ),
) -> (
    BrokerOrderExecutionPolicyActivation
    | BrokerOrderRiskAuthorizationSubject
    | BrokerOrderRiskAuthorizationRecord
):
    """Translate the Broker's ownership/availability failures for the Risk HTTP boundary."""
    try:
        return issue_order_risk_decision(
            request=request, client_order_id=client_order_id, account_id=account_id, command=command
        )
    except BrokerExecutionPermissionError as exc:
        raise AuthorizationError("broker_risk_actor_unavailable") from exc
    except BrokerExecutionConflictError as exc:
        raise BusinessLogicError("broker_risk_order_unavailable") from exc
