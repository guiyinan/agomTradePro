"""Application coverage for ID-only R1 promotion lifecycle transitions."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta

import pytest

from apps.research.application.r1_forecast_promotion import (
    AppendR1PromotionLifecycleCommand,
    AppendR1PromotionLifecycleEventUseCase,
    ExactEquityTrialResultEvidence,
    ExactR1LifecycleAuthorizationEvidence,
    R1ActiveForecastPromotionProvider,
    R1ForecastPromotionDecisionBundle,
    R1PromotionDecisionReceipt,
    R1PromotionEvidenceError,
    R1PromotionLifecycleAction,
    R1PromotionScopeRef,
    R1PromotionVersionRef,
    _equity_trial_record_hash_values,
)
from apps.research.domain.r1_forecast_promotion import (
    R1ForecastPromotionDecision,
    R1PromotionLifecycleEvent,
    R1PromotionLifecycleEventType,
)
from tests.unit.research.test_r1_forecast_promotion import _eligible_result
from tests.unit.research.test_r1_forecast_promotion_application import (
    _PolicyProvider,
    _Repository,
    _TrialProvider,
)
from tests.unit.research.test_r1_forecast_promotion_lifecycle import (
    _authorization,
    _decision,
)


class _AuthorizationProvider:
    def __init__(self, evidence: ExactR1LifecycleAuthorizationEvidence | None) -> None:
        self.evidence = evidence
        self.calls: list[
            tuple[
                R1PromotionVersionRef,
                R1PromotionVersionRef,
                R1PromotionScopeRef,
                R1PromotionLifecycleAction,
                R1PromotionVersionRef,
                R1PromotionVersionRef | None,
            ]
        ] = []

    @property
    def unit_of_work_key(self) -> str:
        return "fake:r1"

    def get_exact(
        self,
        *,
        authorization_ref: R1PromotionVersionRef,
        event_ref: R1PromotionVersionRef,
        scope_ref: R1PromotionScopeRef,
        action: R1PromotionLifecycleAction,
        decision_ref: R1PromotionVersionRef,
        rollback_target_ref: R1PromotionVersionRef | None,
    ) -> ExactR1LifecycleAuthorizationEvidence | None:
        self.calls.append(
            (
                authorization_ref,
                event_ref,
                scope_ref,
                action,
                decision_ref,
                rollback_target_ref,
            )
        )
        return self.evidence


def _version_ref(decision: R1ForecastPromotionDecision) -> R1PromotionVersionRef:
    return R1PromotionVersionRef(decision.decision_id, decision.decision_version)


def _bundle(decision: R1ForecastPromotionDecision) -> R1ForecastPromotionDecisionBundle:
    equity_recorded_at = decision.trial.evaluated_at + timedelta(minutes=1)
    equity_record_hash = _equity_trial_record_hash_values(
        result_id=decision.trial.result_id,
        result_version=decision.trial.result_version,
        result_content_hash=decision.trial.result_content_hash,
        owner="equity",
        recorded_at=equity_recorded_at,
    )
    return R1ForecastPromotionDecisionBundle.create(
        decision=decision,
        receipt=R1PromotionDecisionReceipt.create(
            receipt_id=f"receipt:{decision.decision_id}",
            receipt_version="receipt.v1",
            decision_ref=_version_ref(decision),
            policy_ref=R1PromotionVersionRef(
                decision.policy.policy_id,
                decision.policy.policy_version,
            ),
            policy_content_hash=decision.policy.content_hash,
            result_ref=R1PromotionVersionRef(
                decision.trial.result_id,
                decision.trial.result_version,
            ),
            result_content_hash=decision.trial.result_content_hash,
            equity_result_recorded_at=equity_recorded_at,
            equity_result_record_hash=equity_record_hash,
            decided_at=decision.decided_at,
            recorded_at=decision.recorded_at,
            decision_valid_until=decision.valid_until,
        ),
    )


def _store(repository: _Repository, *decisions: R1ForecastPromotionDecision) -> None:
    for decision in decisions:
        bundle = _bundle(decision)
        repository.records[(decision.decision_id, decision.decision_version)] = bundle


def _evidence(
    *,
    event_ref: R1PromotionVersionRef,
    decision: R1ForecastPromotionDecision,
    action: R1PromotionLifecycleAction,
    occurred_at: datetime,
    reasons: tuple[str, ...],
    rollback_target: R1ForecastPromotionDecision | None = None,
) -> ExactR1LifecycleAuthorizationEvidence:
    authorization = _authorization(
        decision,
        event_type=action.event_type,
        occurred_at=occurred_at,
        reason_codes=reasons,
        rollback_target=rollback_target,
    )
    return ExactR1LifecycleAuthorizationEvidence.create(
        event_ref=event_ref,
        authorization=authorization,
        reason_codes=reasons,
        occurred_at=occurred_at,
        event_recorded_at=occurred_at + timedelta(minutes=1),
    )


def _command(
    *,
    event_ref: R1PromotionVersionRef,
    decision: R1ForecastPromotionDecision,
    evidence: ExactR1LifecycleAuthorizationEvidence,
    action: R1PromotionLifecycleAction,
    rollback_target: R1ForecastPromotionDecision | None = None,
) -> AppendR1PromotionLifecycleCommand:
    return AppendR1PromotionLifecycleCommand(
        output_event_ref=event_ref,
        scope_ref=R1PromotionScopeRef(decision.promotion_scope.scope_id),
        action=action,
        decision_ref=_version_ref(decision),
        authorization_ref=R1PromotionVersionRef(
            evidence.authorization.authorization_id,
            evidence.authorization.authorization_version,
        ),
        rollback_target_ref=(
            _version_ref(rollback_target) if rollback_target is not None else None
        ),
    )


def _append(
    *,
    repository: _Repository,
    command: AppendR1PromotionLifecycleCommand,
    evidence: ExactR1LifecycleAuthorizationEvidence | None,
) -> tuple[R1PromotionLifecycleEvent, _AuthorizationProvider]:
    provider = _AuthorizationProvider(evidence)
    event = AppendR1PromotionLifecycleEventUseCase(
        authorization_provider=provider,
        repository=repository,
    ).execute(command)
    return event, provider


def _append_root(
    repository: _Repository,
    decision: R1ForecastPromotionDecision,
    *,
    suffix: str,
) -> R1PromotionLifecycleEvent:
    event_ref = R1PromotionVersionRef(f"r1-event:{suffix}", "event.v1")
    occurred_at = decision.recorded_at + timedelta(minutes=10)
    evidence = _evidence(
        event_ref=event_ref,
        decision=decision,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=occurred_at,
        reasons=("research_promotion_approved",),
    )
    command = _command(
        event_ref=event_ref,
        decision=decision,
        evidence=evidence,
        action=R1PromotionLifecycleAction.PROMOTE,
    )
    event, _ = _append(
        repository=repository,
        command=command,
        evidence=evidence,
    )
    return event


def _active_provider(
    repository: _Repository,
    decision: R1ForecastPromotionDecision,
) -> R1ActiveForecastPromotionProvider:
    result = _eligible_result()
    evidence = ExactEquityTrialResultEvidence.create(
        result=result,
        recorded_at=decision.trial.evaluated_at + timedelta(minutes=1),
    )
    return R1ActiveForecastPromotionProvider(
        policy_provider=_PolicyProvider(decision.policy),
        trial_result_provider=_TrialProvider(evidence),
        repository=repository,
    )


def test_lifecycle_command_is_id_only_and_root_is_exactly_replayable() -> None:
    decision = _decision("application-root", hour=1)
    repository = _Repository()
    _store(repository, decision)
    event_ref = R1PromotionVersionRef("r1-event:application-root", "event.v1")
    occurred_at = decision.recorded_at + timedelta(minutes=10)
    evidence = _evidence(
        event_ref=event_ref,
        decision=decision,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=occurred_at,
        reasons=("research_promotion_approved",),
    )
    command = _command(
        event_ref=event_ref,
        decision=decision,
        evidence=evidence,
        action=R1PromotionLifecycleAction.PROMOTE,
    )

    first, provider = _append(
        repository=repository,
        command=command,
        evidence=evidence,
    )
    second, _ = _append(
        repository=repository,
        command=command,
        evidence=evidence,
    )

    assert tuple(item.name for item in fields(AppendR1PromotionLifecycleCommand)) == (
        "output_event_ref",
        "scope_ref",
        "action",
        "decision_ref",
        "authorization_ref",
        "rollback_target_ref",
    )
    assert first == second
    assert first.sequence == 1
    assert first.stream_id.endswith(decision.promotion_scope.scope_id)
    assert provider.calls == [
        (
            command.authorization_ref,
            command.output_event_ref,
            command.scope_ref,
            command.action,
            command.decision_ref,
            None,
        )
    ]


def test_replacement_and_exact_rollback_are_resolved_from_repository_ids() -> None:
    first = _decision("application-first", hour=1)
    second = _decision("application-second", hour=2)
    repository = _Repository()
    _store(repository, first, second)

    root_ref = R1PromotionVersionRef("r1-event:application-first", "event.v1")
    root_at = first.recorded_at + timedelta(minutes=10)
    root_evidence = _evidence(
        event_ref=root_ref,
        decision=first,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=root_at,
        reasons=("research_promotion_approved",),
    )
    root_command = _command(
        event_ref=root_ref,
        decision=first,
        evidence=root_evidence,
        action=R1PromotionLifecycleAction.PROMOTE,
    )
    root, _ = _append(
        repository=repository,
        command=root_command,
        evidence=root_evidence,
    )

    promote_ref = R1PromotionVersionRef("r1-event:application-second", "event.v1")
    promote_at = max(root.recorded_at, second.recorded_at) + timedelta(minutes=10)
    promote_evidence = _evidence(
        event_ref=promote_ref,
        decision=second,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=promote_at,
        reasons=("replacement_promotion_approved",),
    )
    promote_command = _command(
        event_ref=promote_ref,
        decision=second,
        evidence=promote_evidence,
        action=R1PromotionLifecycleAction.PROMOTE,
    )
    promoted, _ = _append(
        repository=repository,
        command=promote_command,
        evidence=promote_evidence,
    )

    rollback_ref = R1PromotionVersionRef("r1-event:rollback-second", "event.v1")
    rollback_at = promoted.recorded_at + timedelta(minutes=10)
    rollback_evidence = _evidence(
        event_ref=rollback_ref,
        decision=second,
        action=R1PromotionLifecycleAction.ROLLBACK,
        occurred_at=rollback_at,
        reasons=("replacement_failed_validation",),
        rollback_target=first,
    )
    rollback_command = _command(
        event_ref=rollback_ref,
        decision=second,
        evidence=rollback_evidence,
        action=R1PromotionLifecycleAction.ROLLBACK,
        rollback_target=first,
    )
    rolled_back, _ = _append(
        repository=repository,
        command=rollback_command,
        evidence=rollback_evidence,
    )

    assert (root.sequence, promoted.sequence, rolled_back.sequence) == (1, 2, 3)
    assert rolled_back.rollback_target is not None
    assert rolled_back.rollback_target.content_hash == first.content_hash

    replayed_promoted, _ = _append(
        repository=repository,
        command=promote_command,
        evidence=promote_evidence,
    )
    assert replayed_promoted == promoted

    conflicting_evidence = _evidence(
        event_ref=promote_ref,
        decision=second,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=promote_at,
        reasons=("conflicting_replacement_reason",),
    )
    conflicting_command = _command(
        event_ref=promote_ref,
        decision=second,
        evidence=conflicting_evidence,
        action=R1PromotionLifecycleAction.PROMOTE,
    )
    with pytest.raises(R1PromotionEvidenceError, match="conflicting evidence"):
        _append(
            repository=repository,
            command=conflicting_command,
            evidence=conflicting_evidence,
        )


def test_missing_or_fabricated_authorization_fails_before_append() -> None:
    decision = _decision("application-auth", hour=1)
    repository = _Repository()
    _store(repository, decision)
    event_ref = R1PromotionVersionRef("r1-event:application-auth", "event.v1")
    occurred_at = decision.recorded_at + timedelta(minutes=10)
    evidence = _evidence(
        event_ref=event_ref,
        decision=decision,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=occurred_at,
        reasons=("research_promotion_approved",),
    )
    command = _command(
        event_ref=event_ref,
        decision=decision,
        evidence=evidence,
        action=R1PromotionLifecycleAction.PROMOTE,
    )

    with pytest.raises(R1PromotionEvidenceError, match="authorization is unavailable"):
        _append(repository=repository, command=command, evidence=None)

    other_event_ref = R1PromotionVersionRef("r1-event:fabricated", "event.v1")
    fabricated = _evidence(
        event_ref=other_event_ref,
        decision=decision,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=occurred_at,
        reasons=("research_promotion_approved",),
    )
    with pytest.raises(R1PromotionEvidenceError, match="authorization is unavailable"):
        _append(repository=repository, command=command, evidence=fabricated)
    assert repository.lifecycle_appended == []


def test_wrong_scope_action_decision_target_and_time_fail_closed() -> None:
    first = _decision("application-guard-first", hour=1)
    second = _decision("application-guard-second", hour=2)
    unrelated = _decision("application-guard-unrelated", hour=3)
    repository = _Repository()
    _store(repository, first, second, unrelated)
    event_ref = R1PromotionVersionRef("r1-event:application-guard", "event.v1")
    occurred_at = first.recorded_at + timedelta(minutes=10)
    evidence = _evidence(
        event_ref=event_ref,
        decision=first,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=occurred_at,
        reasons=("research_promotion_approved",),
    )
    command = _command(
        event_ref=event_ref,
        decision=first,
        evidence=evidence,
        action=R1PromotionLifecycleAction.PROMOTE,
    )

    wrong_scope = AppendR1PromotionLifecycleCommand(
        output_event_ref=command.output_event_ref,
        scope_ref=R1PromotionScopeRef("r1v:" + "0" * 64),
        action=command.action,
        decision_ref=command.decision_ref,
        authorization_ref=command.authorization_ref,
        rollback_target_ref=None,
    )
    with pytest.raises(R1PromotionEvidenceError, match="scope was substituted"):
        _append(repository=repository, command=wrong_scope, evidence=evidence)

    wrong_action = AppendR1PromotionLifecycleCommand(
        output_event_ref=command.output_event_ref,
        scope_ref=command.scope_ref,
        action=R1PromotionLifecycleAction.RETIRE,
        decision_ref=command.decision_ref,
        authorization_ref=command.authorization_ref,
        rollback_target_ref=None,
    )
    with pytest.raises(R1PromotionEvidenceError, match="authorization is unavailable"):
        _append(repository=repository, command=wrong_action, evidence=evidence)

    wrong_decision = AppendR1PromotionLifecycleCommand(
        output_event_ref=command.output_event_ref,
        scope_ref=command.scope_ref,
        action=command.action,
        decision_ref=R1PromotionVersionRef("promotion:missing", "decision.v1"),
        authorization_ref=command.authorization_ref,
        rollback_target_ref=None,
    )
    with pytest.raises(R1PromotionEvidenceError, match="decision bundle is unavailable"):
        _append(repository=repository, command=wrong_decision, evidence=evidence)

    rollback_ref = R1PromotionVersionRef("r1-event:guard-rollback", "event.v1")
    rollback_evidence = _evidence(
        event_ref=rollback_ref,
        decision=second,
        action=R1PromotionLifecycleAction.ROLLBACK,
        occurred_at=unrelated.recorded_at + timedelta(minutes=10),
        reasons=("rollback_requested",),
        rollback_target=first,
    )
    rollback_command = AppendR1PromotionLifecycleCommand(
        output_event_ref=rollback_ref,
        scope_ref=command.scope_ref,
        action=R1PromotionLifecycleAction.ROLLBACK,
        decision_ref=_version_ref(second),
        authorization_ref=R1PromotionVersionRef(
            rollback_evidence.authorization.authorization_id,
            rollback_evidence.authorization.authorization_version,
        ),
        rollback_target_ref=_version_ref(unrelated),
    )
    with pytest.raises(R1PromotionEvidenceError, match="authorization is unavailable"):
        _append(
            repository=repository,
            command=rollback_command,
            evidence=rollback_evidence,
        )


def test_expired_decision_and_nonexact_append_fail_closed() -> None:
    decision = _decision("application-temporal", hour=1)
    repository = _Repository()
    _store(repository, decision)
    event_ref = R1PromotionVersionRef("r1-event:application-temporal", "event.v1")
    occurred_at = decision.recorded_at + timedelta(minutes=10)
    evidence = _evidence(
        event_ref=event_ref,
        decision=decision,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=occurred_at,
        reasons=("research_promotion_approved",),
    )
    command = _command(
        event_ref=event_ref,
        decision=decision,
        evidence=evidence,
        action=R1PromotionLifecycleAction.PROMOTE,
    )

    expired_ref = R1PromotionVersionRef("r1-event:expired-decision", "event.v1")
    expired_evidence = _evidence(
        event_ref=expired_ref,
        decision=decision,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=decision.valid_until,
        reasons=("research_promotion_approved",),
    )
    expired = _command(
        event_ref=expired_ref,
        decision=decision,
        evidence=expired_evidence,
        action=R1PromotionLifecycleAction.PROMOTE,
    )
    with pytest.raises(ValueError, match="inactive at occurrence"):
        _append(repository=repository, command=expired, evidence=expired_evidence)

    wrong_event = R1PromotionLifecycleEventType.PROMOTED
    assert wrong_event is evidence.authorization.event_type
    other_repository = _Repository(lifecycle_append_override=None)
    _store(other_repository, decision)
    persisted, _ = _append(
        repository=other_repository,
        command=command,
        evidence=evidence,
    )
    assert persisted == other_repository.lifecycle_appended[0].event
    conflicting_repository = _Repository(
        lifecycle_append_override=other_repository.lifecycle_appended[0]
    )
    _store(conflicting_repository, decision)
    different_ref = R1PromotionVersionRef("r1-event:different-output", "event.v1")
    different_evidence = _evidence(
        event_ref=different_ref,
        decision=decision,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=occurred_at,
        reasons=("research_promotion_approved",),
    )
    different_command = _command(
        event_ref=different_ref,
        decision=decision,
        evidence=different_evidence,
        action=R1PromotionLifecycleAction.PROMOTE,
    )
    with pytest.raises(R1PromotionEvidenceError, match="preserve the exact event bundle"):
        _append(
            repository=conflicting_repository,
            command=different_command,
            evidence=different_evidence,
        )


def test_active_provider_returns_only_recorded_promoted_and_unexpired_bundle() -> None:
    decision = _decision("active-root", hour=1)
    repository = _Repository()
    _store(repository, decision)
    root = _append_root(repository, decision, suffix="active-root")
    provider = _active_provider(repository, decision)
    scope_ref = R1PromotionScopeRef(decision.promotion_scope.scope_id)

    assert (
        provider.get_active(
            scope_ref,
            as_of=root.recorded_at - timedelta(seconds=1),
        )
        is None
    )
    active = provider.get_active(scope_ref, as_of=root.recorded_at)
    assert active == _bundle(decision)
    assert provider.get_active(scope_ref, as_of=decision.valid_until) is None


def test_future_retirement_does_not_rewrite_historical_active_state() -> None:
    decision = _decision("active-retire", hour=1)
    repository = _Repository()
    _store(repository, decision)
    root = _append_root(repository, decision, suffix="active-retire-root")
    provider = _active_provider(repository, decision)
    scope_ref = R1PromotionScopeRef(decision.promotion_scope.scope_id)
    historical_as_of = root.recorded_at

    retire_ref = R1PromotionVersionRef("r1-event:active-retire", "event.v1")
    retire_at = root.recorded_at + timedelta(minutes=10)
    retire_evidence = _evidence(
        event_ref=retire_ref,
        decision=decision,
        action=R1PromotionLifecycleAction.RETIRE,
        occurred_at=retire_at,
        reasons=("research_owner_retired",),
    )
    retire_command = _command(
        event_ref=retire_ref,
        decision=decision,
        evidence=retire_evidence,
        action=R1PromotionLifecycleAction.RETIRE,
    )
    retired, _ = _append(
        repository=repository,
        command=retire_command,
        evidence=retire_evidence,
    )

    assert provider.get_active(scope_ref, as_of=historical_as_of) == _bundle(decision)
    assert provider.get_active(scope_ref, as_of=retired.recorded_at) is None


def test_active_provider_uses_rollback_target_and_fails_on_exact_evidence_gaps() -> None:
    first = _decision("active-first", hour=1)
    second = _decision("active-second", hour=2)
    repository = _Repository()
    _store(repository, first, second)
    root = _append_root(repository, first, suffix="active-first")

    promote_ref = R1PromotionVersionRef("r1-event:active-second", "event.v1")
    promote_at = max(root.recorded_at, second.recorded_at) + timedelta(minutes=10)
    promote_evidence = _evidence(
        event_ref=promote_ref,
        decision=second,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=promote_at,
        reasons=("replacement_promotion_approved",),
    )
    promoted, _ = _append(
        repository=repository,
        command=_command(
            event_ref=promote_ref,
            decision=second,
            evidence=promote_evidence,
            action=R1PromotionLifecycleAction.PROMOTE,
        ),
        evidence=promote_evidence,
    )
    rollback_ref = R1PromotionVersionRef("r1-event:active-rollback", "event.v1")
    rollback_at = promoted.recorded_at + timedelta(minutes=10)
    rollback_evidence = _evidence(
        event_ref=rollback_ref,
        decision=second,
        action=R1PromotionLifecycleAction.ROLLBACK,
        occurred_at=rollback_at,
        reasons=("replacement_failed_validation",),
        rollback_target=first,
    )
    rolled_back, _ = _append(
        repository=repository,
        command=_command(
            event_ref=rollback_ref,
            decision=second,
            evidence=rollback_evidence,
            action=R1PromotionLifecycleAction.ROLLBACK,
            rollback_target=first,
        ),
        evidence=rollback_evidence,
    )
    scope_ref = R1PromotionScopeRef(first.promotion_scope.scope_id)
    provider = _active_provider(repository, first)

    active = provider.get_active(scope_ref, as_of=rolled_back.recorded_at)
    assert active == _bundle(first)
    assert active is not None and active.decision.content_hash != second.content_hash

    missing_policy = R1ActiveForecastPromotionProvider(
        policy_provider=_PolicyProvider(None),
        trial_result_provider=_TrialProvider(
            ExactEquityTrialResultEvidence.create(
                result=_eligible_result(),
                recorded_at=first.trial.evaluated_at + timedelta(minutes=1),
            )
        ),
        repository=repository,
    )
    assert missing_policy.get_active(scope_ref, as_of=rolled_back.recorded_at) is None

    missing_trial = R1ActiveForecastPromotionProvider(
        policy_provider=_PolicyProvider(first.policy),
        trial_result_provider=_TrialProvider(None),
        repository=repository,
    )
    assert missing_trial.get_active(scope_ref, as_of=rolled_back.recorded_at) is None

    substituted_repository = _Repository()
    substituted_repository.lifecycle_bundles = dict(repository.lifecycle_bundles)
    substituted_repository.records[(first.decision_id, first.decision_version)] = _bundle(second)
    substituted_provider = _active_provider(substituted_repository, first)
    assert (
        substituted_provider.get_active(
            scope_ref,
            as_of=rolled_back.recorded_at,
        )
        is None
    )


def test_active_provider_returns_none_for_empty_scope() -> None:
    decision = _decision("active-empty", hour=1)
    provider = _active_provider(_Repository(), decision)

    assert (
        provider.get_active(
            R1PromotionScopeRef(decision.promotion_scope.scope_id),
            as_of=decision.recorded_at,
        )
        is None
    )
