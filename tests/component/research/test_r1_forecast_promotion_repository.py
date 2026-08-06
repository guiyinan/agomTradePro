"""Component contracts for the Research R1 promotion append-only ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from apps.equity.domain.forecast_baseline import ForecastBaselineTrialResult
from apps.equity.infrastructure.forecast_baseline_codec import seal_approval_evidence
from apps.equity.infrastructure.forecast_baseline_query import (
    DjangoExactForecastBaselineTrialQuery,
)
from apps.equity.infrastructure.forecast_baseline_repository import (
    DjangoForecastBaselineRepository,
)
from apps.research.application.r1_forecast_promotion import (
    AppendR1PromotionLifecycleCommand,
    AppendR1PromotionLifecycleEventUseCase,
    EvaluateR1ForecastPromotionCommand,
    EvaluateR1ForecastPromotionUseCase,
    R1PromotionLifecycleAction,
    R1PromotionScopeRef,
    R1PromotionVersionRef,
)
from apps.research.domain.r1_forecast_promotion import (
    R1ForecastPromotionDecision,
    R1ForecastPromotionPolicy,
    R1PromotionLifecycleAuthorization,
    R1PromotionLifecycleEvent,
    R1PromotionLifecycleEventType,
)
from apps.research.infrastructure.r1_forecast_promotion_models import (
    R1ForecastPromotionDecisionBundleModel,
    R1ForecastPromotionPolicyModel,
    R1PromotionDecisionReceiptModel,
    R1PromotionLifecycleEventBundleModel,
    R1PromotionLifecycleReceiptModel,
)
from apps.research.infrastructure.r1_forecast_promotion_repository import (
    DjangoExactEquityTrialResultProvider,
    DjangoR1DecisionReceiptProvider,
    DjangoR1ForecastPromotionRepository,
    DjangoR1LifecycleAuthorizationProvider,
    DjangoR1PromotionPolicyProvider,
    R1LifecycleAuthorizationClaim,
    R1PromotionRepositoryConflict,
    r1_lifecycle_authorization_claim_id,
)
from tests.unit.equity.test_forecast_baseline_application import (
    _approval,
    _evaluate_trial,
)
from tests.unit.research.test_r1_forecast_promotion import _policy

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class _AuthorizationSource:
    claim: R1LifecycleAuthorizationClaim

    def get_exact(
        self,
        *,
        authorization_ref: R1PromotionVersionRef,
        event_ref: R1PromotionVersionRef,
        scope_ref: R1PromotionScopeRef,
        action: R1PromotionLifecycleAction,
        decision_ref: R1PromotionVersionRef,
        rollback_target_ref: R1PromotionVersionRef | None,
    ) -> R1LifecycleAuthorizationClaim | None:
        authorization = self.claim.authorization
        target = authorization.rollback_target
        expected_target_ref = (
            R1PromotionVersionRef(target.decision_id, target.decision_version)
            if target is not None
            else None
        )
        if (
            (authorization.authorization_id, authorization.authorization_version)
            != (authorization_ref.stable_id, authorization_ref.version)
            or authorization.promotion_scope.scope_id != scope_ref.scope_id
            or authorization.event_type is not action.event_type
            or (authorization.decision.decision_id, authorization.decision.decision_version)
            != (decision_ref.stable_id, decision_ref.version)
            or rollback_target_ref != expected_target_ref
        ):
            return None
        return self.claim


@dataclass(frozen=True)
class _Runtime:
    repository: DjangoR1ForecastPromotionRepository
    equity_provider: DjangoExactEquityTrialResultProvider
    policy: R1ForecastPromotionPolicy
    trial: ForecastBaselineTrialResult
    trial_recorded_at: datetime
    command: EvaluateR1ForecastPromotionCommand


def _runtime() -> _Runtime:
    approval = seal_approval_evidence(_approval())
    spec, artifact, trial, *_ = _evaluate_trial(approval=approval)
    equity_repository = DjangoForecastBaselineRepository()
    with patch(
        "apps.equity.infrastructure.forecast_baseline_models.timezone.now",
        return_value=approval.recorded_at,
    ):
        equity_repository.append_approval(approval)
    equity_repository.append_spec(spec)
    equity_repository.append_artifact(artifact)
    trial_recorded_at = trial.evaluated_at + timedelta(minutes=1)
    with patch(
        "django.db.models.fields.timezone.now",
        return_value=trial_recorded_at,
    ):
        equity_repository.append_trial(trial)
    equity_provider = DjangoExactEquityTrialResultProvider(DjangoExactForecastBaselineTrialQuery())
    repository = DjangoR1ForecastPromotionRepository(equity_trial_provider=equity_provider)
    policy = _policy(result=trial)
    repository.append_policy(policy)
    command = EvaluateR1ForecastPromotionCommand(
        output_decision_ref=R1PromotionVersionRef(
            "research-r1-promotion:component",
            "decision.v1",
        ),
        policy_ref=R1PromotionVersionRef(policy.policy_id, policy.policy_version),
        equity_result_ref=R1PromotionVersionRef(trial.result_id, trial.result_version),
        as_of=trial.evaluated_at + timedelta(hours=1),
    )
    return _Runtime(
        repository=repository,
        equity_provider=equity_provider,
        policy=policy,
        trial=trial,
        trial_recorded_at=trial_recorded_at,
        command=command,
    )


def _evaluate(runtime: _Runtime) -> R1ForecastPromotionDecision:
    decided_receipt_at = runtime.command.as_of + timedelta(minutes=1)
    use_case = EvaluateR1ForecastPromotionUseCase(
        policy_provider=DjangoR1PromotionPolicyProvider(runtime.repository),
        trial_result_provider=runtime.equity_provider,
        receipt_provider=DjangoR1DecisionReceiptProvider(runtime.repository),
        repository=runtime.repository,
    )
    with (
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_repository.timezone.now",
            return_value=decided_receipt_at,
        ),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
            return_value=decided_receipt_at,
        ),
    ):
        return use_case.execute(runtime.command)


def _lifecycle_inputs(
    decision: R1ForecastPromotionDecision,
) -> tuple[
    AppendR1PromotionLifecycleCommand,
    _AuthorizationSource,
    datetime,
]:
    event_ref = R1PromotionVersionRef(
        "research-r1-promotion-event:component",
        "event.v1",
    )
    occurred_at = decision.recorded_at + timedelta(minutes=10)
    reasons = ("research_promotion_approved",)
    provisional = R1PromotionLifecycleAuthorization.create(
        authorization_id="r1-lifecycle-authorization:provisional",
        authorization_version="authorization.v1",
        owner="research",
        capability="r1",
        purpose="valuation",
        event_type=R1PromotionLifecycleEventType.PROMOTED,
        decision=decision,
        rollback_target=None,
        reason_codes=reasons,
        issued_at=occurred_at - timedelta(minutes=2),
        recorded_at=occurred_at - timedelta(minutes=1),
        valid_until=occurred_at + timedelta(hours=1),
    )
    authorization = R1PromotionLifecycleAuthorization.create(
        authorization_id=r1_lifecycle_authorization_claim_id(
            event_ref=event_ref,
            authorization=provisional,
        ),
        authorization_version="authorization.v1",
        owner="research",
        capability="r1",
        purpose="valuation",
        event_type=R1PromotionLifecycleEventType.PROMOTED,
        decision=decision,
        rollback_target=None,
        reason_codes=reasons,
        issued_at=provisional.issued_at,
        recorded_at=provisional.recorded_at,
        valid_until=provisional.valid_until,
    )
    command = AppendR1PromotionLifecycleCommand(
        output_event_ref=event_ref,
        scope_ref=R1PromotionScopeRef(decision.promotion_scope.scope_id),
        action=R1PromotionLifecycleAction.PROMOTE,
        decision_ref=R1PromotionVersionRef(
            decision.decision_id,
            decision.decision_version,
        ),
        authorization_ref=R1PromotionVersionRef(
            authorization.authorization_id,
            authorization.authorization_version,
        ),
        rollback_target_ref=None,
    )
    return (
        command,
        _AuthorizationSource(R1LifecycleAuthorizationClaim(authorization, reasons)),
        occurred_at,
    )


def _append_lifecycle(
    runtime: _Runtime,
    decision: R1ForecastPromotionDecision,
) -> R1PromotionLifecycleEvent:
    command, source, occurred_at = _lifecycle_inputs(decision)
    provider = DjangoR1LifecycleAuthorizationProvider(
        runtime.repository,
        owner_source=source,
    )
    use_case = AppendR1PromotionLifecycleEventUseCase(
        authorization_provider=provider,
        repository=runtime.repository,
    )
    with (
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_repository.timezone.now",
            return_value=occurred_at,
        ),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
            return_value=occurred_at,
        ),
    ):
        return use_case.execute(command)


def test_policy_decision_and_lifecycle_event_round_trip() -> None:
    """Concrete Equity evidence supports the complete Research R1 ledger path."""

    runtime = _runtime()
    decision = _evaluate(runtime)
    event = _append_lifecycle(runtime, decision)

    assert R1ForecastPromotionPolicyModel._default_manager.count() == 1
    assert R1PromotionDecisionReceiptModel._default_manager.count() == 1
    assert R1ForecastPromotionDecisionBundleModel._default_manager.count() == 1
    assert R1PromotionLifecycleReceiptModel._default_manager.count() == 1
    assert R1PromotionLifecycleEventBundleModel._default_manager.count() == 1
    assert (
        runtime.repository.get_decision_bundle(
            runtime.command.output_decision_ref,
            as_of=decision.recorded_at,
        ).decision
        == decision
    )
    restored = runtime.repository.get_lifecycle_event_bundle(
        R1PromotionVersionRef(event.event_id, event.event_version)
    )
    assert restored is not None and restored.event == event
    assert runtime.repository.load_lifecycle_stream(
        R1PromotionScopeRef(decision.promotion_scope.scope_id)
    ) == (event,)


def test_decision_child_failure_rolls_back_owner_receipt() -> None:
    """A child append failure cannot leave an orphan decision receipt claim."""

    runtime = _runtime()
    decided_receipt_at = runtime.command.as_of + timedelta(minutes=1)
    use_case = EvaluateR1ForecastPromotionUseCase(
        policy_provider=DjangoR1PromotionPolicyProvider(runtime.repository),
        trial_result_provider=runtime.equity_provider,
        receipt_provider=DjangoR1DecisionReceiptProvider(runtime.repository),
        repository=runtime.repository,
    )
    with (
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_repository.timezone.now",
            return_value=decided_receipt_at,
        ),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
            return_value=decided_receipt_at,
        ),
        patch.object(
            runtime.repository,
            "append_decision_bundle",
            side_effect=RuntimeError("injected child failure"),
        ),
        pytest.raises(RuntimeError, match="injected child failure"),
    ):
        use_case.execute(runtime.command)

    assert R1PromotionDecisionReceiptModel._default_manager.count() == 0
    assert R1ForecastPromotionDecisionBundleModel._default_manager.count() == 0


def test_lifecycle_child_failure_rolls_back_authorization_receipt() -> None:
    """A child append failure cannot leave an orphan lifecycle receipt claim."""

    runtime = _runtime()
    decision = _evaluate(runtime)
    command, source, occurred_at = _lifecycle_inputs(decision)
    provider = DjangoR1LifecycleAuthorizationProvider(
        runtime.repository,
        owner_source=source,
    )
    use_case = AppendR1PromotionLifecycleEventUseCase(
        authorization_provider=provider,
        repository=runtime.repository,
    )
    with (
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_repository.timezone.now",
            return_value=occurred_at,
        ),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
            return_value=occurred_at,
        ),
        patch.object(
            runtime.repository,
            "append_lifecycle_event_bundle",
            side_effect=RuntimeError("injected lifecycle child failure"),
        ),
        pytest.raises(RuntimeError, match="injected lifecycle child failure"),
    ):
        use_case.execute(command)

    assert R1PromotionLifecycleReceiptModel._default_manager.count() == 0
    assert R1PromotionLifecycleEventBundleModel._default_manager.count() == 0


def test_public_claim_providers_require_repository_owned_unit_of_work() -> None:
    """Standalone provider calls fail before either receipt table can be written."""

    runtime = _runtime()
    evidence = runtime.equity_provider.get_exact(
        runtime.command.equity_result_ref,
        as_of=runtime.command.as_of,
    )
    assert evidence is not None
    with pytest.raises(R1PromotionRepositoryConflict, match="unit of work"):
        DjangoR1DecisionReceiptProvider(runtime.repository).get_exact(
            decision_ref=runtime.command.output_decision_ref,
            policy_ref=runtime.command.policy_ref,
            policy_content_hash=runtime.policy.content_hash,
            result_ref=runtime.command.equity_result_ref,
            result_content_hash=runtime.trial.content_hash,
            equity_result_recorded_at=evidence.recorded_at,
            equity_result_record_hash=evidence.record_hash,
            decided_at=runtime.command.as_of,
            decision_valid_until=runtime.command.as_of + timedelta(days=1),
        )
    assert R1PromotionDecisionReceiptModel._default_manager.count() == 0


def test_repository_rejects_cross_database_equity_record_bindings() -> None:
    """Opaque Equity primary keys cannot cross database aliases."""

    provider = DjangoExactEquityTrialResultProvider(
        DjangoExactForecastBaselineTrialQuery(using="other")
    )
    with pytest.raises(ValueError, match="share one database"):
        DjangoR1ForecastPromotionRepository(
            equity_trial_provider=provider,
            using="default",
        )
