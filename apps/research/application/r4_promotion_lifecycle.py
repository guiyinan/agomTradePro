"""ID-only orchestration and active resolution for the R4 lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.portfolio.application.macro_risk_rolling_research import (
    ExactR3PromotionProvider,
)
from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchExactQuery,
)
from apps.research.application.r4_promotion_decision import (
    ExactR4PromotionPolicyProvider,
    R4PromotionDecisionBundle,
    R4PromotionEvidenceError,
    R4PromotionVersionRef,
)
from apps.research.application.r4_promotion_lifecycle_evidence import (
    ExactR4LifecycleAuthorizationEvidence,
    ExactR4LifecycleAuthorizationProvider,
    R4PromotionLifecycleAction,
    R4PromotionLifecycleEventBundle,
    R4PromotionLifecycleRepository,
    R4PromotionScopeRef,
    exact_r4_lifecycle_authorization_evidence_hash,
)
from apps.research.application.r4_promotion_projection import (
    project_r4_portfolio_owner_record,
    project_r4_promotion_r3_attestation,
)
from apps.research.domain.r4_promotion_decision import (
    R4PromotionDecision,
    R4PromotionDecisionOutcome,
    create_r4_promotion_decision,
)
from apps.research.domain.r4_promotion_lifecycle import (
    R4PromotionDecisionIdentity,
    R4PromotionLifecycleEvent,
    R4PromotionLifecycleState,
    create_r4_promotion_lifecycle_event,
    create_r4_promotion_lifecycle_root,
    derive_r4_promotion_lifecycle_state,
    r4_promotion_stream_id,
)
from apps.research.domain.r4_promotion_scope_policy import _require_aware
from apps.research.domain.r4_promotion_trial import R4PromotionTrialSeal


@dataclass(frozen=True)
class AppendR4PromotionLifecycleCommand:
    """ID-only lifecycle request; owner providers supply evidence and clocks."""

    output_event_ref: R4PromotionVersionRef
    scope_ref: R4PromotionScopeRef
    action: R4PromotionLifecycleAction
    decision_ref: R4PromotionVersionRef
    authorization_ref: R4PromotionVersionRef
    rollback_target_ref: R4PromotionVersionRef | None

    def __post_init__(self) -> None:
        if self.action is R4PromotionLifecycleAction.ROLLBACK:
            if self.rollback_target_ref is None:
                raise ValueError("R4 rollback lifecycle command requires a target ref")
        elif self.rollback_target_ref is not None:
            raise ValueError("non-rollback R4 lifecycle command cannot carry a target ref")


class AppendR4PromotionLifecycleEventUseCase:
    """Re-read every exact owner dependency before one lifecycle append."""

    def __init__(
        self,
        *,
        policy_provider: ExactR4PromotionPolicyProvider,
        portfolio_query: R4RollingResearchExactQuery,
        current_r3_provider: ExactR3PromotionProvider,
        authorization_provider: ExactR4LifecycleAuthorizationProvider,
        repository: R4PromotionLifecycleRepository,
    ) -> None:
        self._policy_provider = policy_provider
        self._portfolio_query = portfolio_query
        self._current_r3_provider = current_r3_provider
        self._authorization_provider = authorization_provider
        self._repository = repository
        unit_of_work_keys = {
            portfolio_query.unit_of_work_key,
            authorization_provider.unit_of_work_key,
            repository.unit_of_work_key,
        }
        if len(unit_of_work_keys) != 1:
            raise ValueError(
                "R4 portfolio query, lifecycle authorization and repository "
                "use different units of work"
            )

    def execute(
        self,
        command: AppendR4PromotionLifecycleCommand,
    ) -> R4PromotionLifecycleEvent:
        """Claim owner evidence, replay the prefix and append atomically."""

        with self._repository.atomic():
            return self._append_atomic(command)

    def _append_atomic(
        self,
        command: AppendR4PromotionLifecycleCommand,
    ) -> R4PromotionLifecycleEvent:
        evidence = self._authorization_provider.get_exact(
            authorization_ref=command.authorization_ref,
            event_ref=command.output_event_ref,
            scope_ref=command.scope_ref,
            action=command.action,
            decision_ref=command.decision_ref,
            rollback_target_ref=command.rollback_target_ref,
        )
        if evidence is None:
            raise R4PromotionEvidenceError(
                "exact Research R4 lifecycle authorization is unavailable"
            )
        knowledge_at = evidence.occurred_at
        decision_bundle = _load_revalidated_decision_bundle(
            decision_ref=command.decision_ref,
            as_of=knowledge_at,
            require_current=command.action is not R4PromotionLifecycleAction.RETIRE,
            policy_provider=self._policy_provider,
            portfolio_query=self._portfolio_query,
            current_r3_provider=self._current_r3_provider,
            repository=self._repository,
        )
        decision = decision_bundle.decision
        if decision.scope.scope_id != command.scope_ref.scope_id:
            raise R4PromotionEvidenceError("R4 lifecycle decision scope was substituted")
        rollback_target: R4PromotionDecision | None = None
        if command.rollback_target_ref is not None:
            rollback_target = _load_revalidated_decision_bundle(
                decision_ref=command.rollback_target_ref,
                as_of=knowledge_at,
                require_current=True,
                policy_provider=self._policy_provider,
                portfolio_query=self._portfolio_query,
                current_r3_provider=self._current_r3_provider,
                repository=self._repository,
            ).decision
            if rollback_target.scope != decision.scope:
                raise R4PromotionEvidenceError("R4 lifecycle rollback target crosses scopes")
        if not _authorization_matches(
            evidence=evidence,
            command=command,
            decision=decision,
            rollback_target=rollback_target,
        ):
            raise R4PromotionEvidenceError(
                "exact Research R4 lifecycle authorization is unavailable"
            )
        existing_bundle = self._repository.get_lifecycle_event_bundle(command.output_event_ref)
        if existing_bundle is not None:
            return self._validate_existing(
                existing_bundle=existing_bundle,
                evidence=evidence,
                command=command,
                decision=decision,
                rollback_target=rollback_target,
            )
        history = self._repository.load_lifecycle_history(
            command.scope_ref,
            as_of=knowledge_at,
        )
        if any(item.recorded_at > knowledge_at for item in history):
            raise R4PromotionEvidenceError("R4 lifecycle history contains future evidence")
        if not history:
            if command.action is not R4PromotionLifecycleAction.PROMOTE:
                raise R4PromotionEvidenceError("R4 lifecycle stream must start with promotion")
            event = create_r4_promotion_lifecycle_root(
                event_id=command.output_event_ref.stable_id,
                event_version=command.output_event_ref.version,
                decision=decision,
                authorization=evidence.authorization,
                reason_codes=evidence.reason_codes,
                occurred_at=evidence.occurred_at,
                recorded_at=evidence.event_recorded_at,
            )
        else:
            try:
                derive_r4_promotion_lifecycle_state(
                    history,
                    evaluated_at=knowledge_at,
                )
            except ValueError as error:
                raise R4PromotionEvidenceError(
                    "R4 lifecycle prefix failed canonical replay"
                ) from error
            event = create_r4_promotion_lifecycle_event(
                event_id=command.output_event_ref.stable_id,
                event_version=command.output_event_ref.version,
                previous_events=history,
                event_type=command.action.event_type,
                decision=decision,
                rollback_target=rollback_target,
                authorization=evidence.authorization,
                reason_codes=evidence.reason_codes,
                occurred_at=evidence.occurred_at,
                recorded_at=evidence.event_recorded_at,
            )
        bundle = R4PromotionLifecycleEventBundle.create(
            event=event,
            evidence=evidence,
        )
        persisted = self._repository.append_lifecycle_event_bundle(bundle)
        if persisted != bundle:
            raise R4PromotionEvidenceError("R4 lifecycle repository changed the exact event bundle")
        return persisted.event

    def _validate_existing(
        self,
        *,
        existing_bundle: R4PromotionLifecycleEventBundle,
        evidence: ExactR4LifecycleAuthorizationEvidence,
        command: AppendR4PromotionLifecycleCommand,
        decision: R4PromotionDecision,
        rollback_target: R4PromotionDecision | None,
    ) -> R4PromotionLifecycleEvent:
        existing = existing_bundle.event
        if not _event_matches_evidence(
            event=existing,
            evidence=evidence,
            command=command,
            decision=decision,
            rollback_target=rollback_target,
        ):
            raise R4PromotionEvidenceError("R4 lifecycle output identity has conflicting evidence")
        if existing_bundle != R4PromotionLifecycleEventBundle.create(
            event=existing,
            evidence=evidence,
        ):
            raise R4PromotionEvidenceError("existing R4 lifecycle event receipt was substituted")
        full_stream = self._repository.load_lifecycle_stream(command.scope_ref)
        if existing not in full_stream:
            raise R4PromotionEvidenceError("existing R4 lifecycle event is missing from its stream")
        try:
            derive_r4_promotion_lifecycle_state(
                full_stream,
                evaluated_at=max(item.recorded_at for item in full_stream),
            )
        except ValueError as error:
            raise R4PromotionEvidenceError(
                "existing R4 lifecycle stream failed canonical replay"
            ) from error
        return existing


class R4ActivePromotionProvider:
    """Resolve one exact current R4 promotion by scope and PIT replay."""

    def __init__(
        self,
        *,
        policy_provider: ExactR4PromotionPolicyProvider,
        portfolio_query: R4RollingResearchExactQuery,
        current_r3_provider: ExactR3PromotionProvider,
        repository: R4PromotionLifecycleRepository,
    ) -> None:
        self._policy_provider = policy_provider
        self._portfolio_query = portfolio_query
        self._current_r3_provider = current_r3_provider
        self._repository = repository
        if portfolio_query.unit_of_work_key != repository.unit_of_work_key:
            raise ValueError(
                "R4 portfolio query and lifecycle repository use different units of work"
            )

    def get_active(
        self,
        scope_ref: R4PromotionScopeRef,
        *,
        as_of: datetime,
    ) -> R4PromotionDecisionBundle | None:
        """Replay the prefix and fail closed on any exact owner-evidence gap."""

        _require_aware(as_of, "active R4 promotion as_of")
        with self._repository.atomic():
            try:
                history = self._repository.load_lifecycle_history(
                    scope_ref,
                    as_of=as_of,
                )
                if not history or any(item.recorded_at > as_of for item in history):
                    return None
                snapshot = derive_r4_promotion_lifecycle_state(
                    history,
                    evaluated_at=as_of,
                )
                identity = snapshot.active_decision
                if (
                    snapshot.state
                    not in {
                        R4PromotionLifecycleState.PROMOTED,
                        R4PromotionLifecycleState.ROLLED_BACK,
                    }
                    or identity is None
                ):
                    return None
                bundle = _load_revalidated_decision_bundle(
                    decision_ref=R4PromotionVersionRef(
                        identity.decision_id,
                        identity.decision_version,
                    ),
                    as_of=as_of,
                    require_current=True,
                    policy_provider=self._policy_provider,
                    portfolio_query=self._portfolio_query,
                    current_r3_provider=self._current_r3_provider,
                    repository=self._repository,
                )
                decision = bundle.decision
                if (
                    R4PromotionDecisionIdentity.from_decision(decision) != identity
                    or decision.scope.scope_id != scope_ref.scope_id
                ):
                    return None
                return bundle
            except ValueError:
                return None


def _load_revalidated_decision_bundle(
    *,
    decision_ref: R4PromotionVersionRef,
    as_of: datetime,
    require_current: bool,
    policy_provider: ExactR4PromotionPolicyProvider,
    portfolio_query: R4RollingResearchExactQuery,
    current_r3_provider: ExactR3PromotionProvider,
    repository: R4PromotionLifecycleRepository,
) -> R4PromotionDecisionBundle:
    bundle = repository.get_decision_bundle(decision_ref, as_of=as_of)
    if bundle is None or (
        bundle.decision.decision_id,
        bundle.decision.decision_version,
    ) != (decision_ref.stable_id, decision_ref.version):
        raise R4PromotionEvidenceError("exact R4 promotion decision is unavailable")
    decision = bundle.decision
    try:
        canonical_bundle = R4PromotionDecisionBundle.create(
            decision=decision,
            receipt=bundle.receipt,
        )
    except ValueError as error:
        raise R4PromotionEvidenceError("R4 decision bundle is not canonical") from error
    if (
        bundle != canonical_bundle
        or decision.outcome is not R4PromotionDecisionOutcome.APPROVED
        or decision.recorded_at > as_of
        or (require_current and not decision.recorded_at <= as_of < decision.valid_until)
    ):
        raise R4PromotionEvidenceError("R4 decision is not exact, approved and active")
    owner_as_of = as_of if require_current else decision.decided_at
    policy_ref = R4PromotionVersionRef(
        decision.policy.policy_id,
        decision.policy.policy_version,
    )
    policy = policy_provider.get_exact(policy_ref, as_of=owner_as_of)
    if policy is None:
        raise R4PromotionEvidenceError("exact policy is unavailable")
    if policy != decision.policy or not policy.is_active_at(owner_as_of):
        raise R4PromotionEvidenceError("exact policy was substituted or is inactive")
    owner_record = portfolio_query.get_exact(
        record_id=decision.trial.portfolio_record.record_id,
        expected_record_hash=decision.trial.portfolio_record.record_hash,
        as_of=owner_as_of,
    )
    if owner_record is None:
        raise R4PromotionEvidenceError("exact portfolio record is unavailable")
    portfolio_record = project_r4_portfolio_owner_record(owner_record)
    if (
        portfolio_record != decision.trial.portfolio_record
        or not portfolio_record.recorded_at <= owner_as_of < portfolio_record.valid_until
    ):
        raise R4PromotionEvidenceError("exact portfolio record was substituted or is inactive")
    source = owner_record.record.promotion_attestation
    current_r3 = current_r3_provider.get_exact(
        capability_key="macro_factor_r3",
        artifact_id=source.artifact_id,
        artifact_version=source.artifact_version,
        artifact_content_hash=source.artifact_content_hash,
        decision_id=source.decision_id,
        decision_version=source.decision_version,
        decision_content_hash=source.decision_content_hash,
        as_of=owner_as_of,
    )
    if current_r3 is None:
        raise R4PromotionEvidenceError("exact current r3 attestation is unavailable")
    current_r3_evidence = project_r4_promotion_r3_attestation(current_r3)
    if (
        current_r3_evidence != decision.trial.current_r3_attestation
        or current_r3_evidence != portfolio_record.record_r3_attestation
        or not current_r3_evidence.is_active_at(owner_as_of)
    ):
        raise R4PromotionEvidenceError(
            "exact current r3 attestation was substituted or is inactive"
        )
    try:
        rebuilt_trial = R4PromotionTrialSeal.create(
            trial_id=decision.trial.trial_id,
            trial_version=decision.trial.trial_version,
            policy=policy,
            portfolio_record=portfolio_record,
            current_r3_attestation=current_r3_evidence,
            evaluated_at=decision.trial.evaluated_at,
        )
        rebuilt_decision = create_r4_promotion_decision(
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            policy=policy,
            trial=rebuilt_trial,
            as_of=decision.decided_at,
            recorded_at=decision.recorded_at,
        )
    except ValueError as error:
        raise R4PromotionEvidenceError(
            "R4 trial or decision cannot be rebuilt from exact owner evidence"
        ) from error
    if rebuilt_trial != decision.trial or rebuilt_decision != decision:
        raise R4PromotionEvidenceError("R4 trial or decision derived state was substituted")
    return bundle


def _authorization_matches(
    *,
    evidence: ExactR4LifecycleAuthorizationEvidence,
    command: AppendR4PromotionLifecycleCommand,
    decision: R4PromotionDecision,
    rollback_target: R4PromotionDecision | None,
) -> bool:
    authorization = evidence.authorization
    target_identity = (
        None
        if rollback_target is None
        else R4PromotionDecisionIdentity.from_decision(rollback_target)
    )
    return (
        evidence.event_ref == command.output_event_ref
        and (
            authorization.authorization_id,
            authorization.authorization_version,
        )
        == (
            command.authorization_ref.stable_id,
            command.authorization_ref.version,
        )
        and authorization.owner == "research"
        and authorization.capability == "r4"
        and authorization.purpose == "macro_risk_method_research"
        and authorization.event_type is command.action.event_type
        and authorization.scope.scope_id == command.scope_ref.scope_id
        and authorization.decision == R4PromotionDecisionIdentity.from_decision(decision)
        and authorization.rollback_target == target_identity
        and authorization.recorded_at <= evidence.occurred_at
        and evidence.content_hash == exact_r4_lifecycle_authorization_evidence_hash(evidence)
    )


def _event_matches_evidence(
    *,
    event: R4PromotionLifecycleEvent,
    evidence: ExactR4LifecycleAuthorizationEvidence,
    command: AppendR4PromotionLifecycleCommand,
    decision: R4PromotionDecision,
    rollback_target: R4PromotionDecision | None,
) -> bool:
    target_identity = (
        None
        if rollback_target is None
        else R4PromotionDecisionIdentity.from_decision(rollback_target)
    )
    return (
        (event.event_id, event.event_version)
        == (command.output_event_ref.stable_id, command.output_event_ref.version)
        and event.scope.scope_id == command.scope_ref.scope_id
        and event.stream_id == r4_promotion_stream_id(decision.scope)
        and event.event_type is command.action.event_type
        and event.decision == R4PromotionDecisionIdentity.from_decision(decision)
        and event.rollback_target == target_identity
        and event.authorization == evidence.authorization
        and event.reason_codes == evidence.reason_codes
        and event.occurred_at == evidence.occurred_at
        and event.recorded_at == evidence.event_recorded_at
    )


__all__ = [
    "AppendR4PromotionLifecycleCommand",
    "AppendR4PromotionLifecycleEventUseCase",
    "R4ActivePromotionProvider",
]
