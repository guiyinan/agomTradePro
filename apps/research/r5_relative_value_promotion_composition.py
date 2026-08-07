"""Concrete Django composition for persisted R5 promotion research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.fixed_income.application.relative_value_projection import (
    project_r5_relative_value_owner_record,
)
from apps.research.application.r5_relative_value_promotion_decision import (
    EvaluateR5RelativeValuePromotion,
    ExactR5PortfolioOutcomeProvider,
    ExactR5RelativeValueDecisionAuthorizationProvider,
    ExactR5RelativeValueOwnerRecordProvider,
    ExactR5RelativeValuePromotionPolicyProvider,
    ExactR5RelativeValuePromotionTrialProvider,
    R5RelativeValueDecisionAuthorization,
    R5RelativeValuePromotionRef,
    r5_relative_value_decision_authorization_hash,
)
from apps.research.application.r5_relative_value_promotion_lifecycle import (
    ApplyR5RelativeValuePromotionLifecycle,
    ExactR5RelativeValueLifecycleAuthorizationProvider,
    GetActiveR5RelativeValuePromotion,
    R5RelativeValueLifecycleAction,
    R5RelativeValueLifecycleAuthorizationEvidence,
    R5RelativeValueLifecycleScopeRef,
    r5_relative_value_lifecycle_evidence_hash,
)
from apps.research.application.r5_relative_value_promotion_persistence import (
    ExactR5PromotionArtifactSource,
    R5PromotionArtifact,
    R5PromotionArtifactKind,
    RegisterR5PromotionArtifact,
    RegisterR5PromotionArtifactCommand,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
)
from apps.research.infrastructure.r5_relative_value_promotion_codec import (
    decode_r5_promotion_artifact,
    encode_r5_promotion_artifact,
)
from apps.research.infrastructure.r5_relative_value_promotion_repository import (
    DjangoR5DecisionAuthorizationProvider,
    DjangoR5PromotionPolicyProvider,
    DjangoR5PromotionRepository,
    DjangoR5PromotionServerClock,
    DjangoR5PromotionTrialProvider,
    R5PromotionRepositoryConflict,
    R5PromotionServerClock,
)


class _HybridDecisionAuthorizationProvider:
    """Use persisted evidence after first append, exact owner source before it."""

    def __init__(
        self,
        *,
        persisted: DjangoR5DecisionAuthorizationProvider,
        source: ExactR5RelativeValueDecisionAuthorizationProvider,
    ) -> None:
        self._persisted = persisted
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        return self._persisted.unit_of_work_key

    def get_exact(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        policy_ref: R5RelativeValuePromotionRef,
        trial_ref: R5RelativeValuePromotionRef,
        as_of: datetime,
    ) -> R5RelativeValueDecisionAuthorization | None:
        persisted = self._persisted.get_exact(
            authorization_ref=authorization_ref,
            policy_ref=policy_ref,
            trial_ref=trial_ref,
            as_of=as_of,
        )
        if persisted is not None:
            return persisted
        authorization = self._source.get_exact(
            authorization_ref=authorization_ref,
            policy_ref=policy_ref,
            trial_ref=trial_ref,
            as_of=as_of,
        )
        if authorization is None:
            return None
        try:
            if (
                (authorization.authorization_id, authorization.authorization_version)
                != (authorization_ref.stable_id, authorization_ref.version)
                or authorization.policy_ref != policy_ref
                or authorization.trial_ref != trial_ref
                or authorization.content_hash
                != r5_relative_value_decision_authorization_hash(authorization)
            ):
                raise ValueError("decision authorization source substitution")
        except (AttributeError, TypeError, ValueError) as error:
            raise R5PromotionRepositoryConflict(
                "decision authorization source returned noncanonical evidence"
            ) from error
        return authorization


class _HybridLifecycleAuthorizationProvider:
    """Use an immutable stored receipt after the first event append."""

    def __init__(
        self,
        *,
        repository: DjangoR5PromotionRepository,
        source: ExactR5RelativeValueLifecycleAuthorizationProvider,
    ) -> None:
        self._repository = repository
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        scope_ref: R5RelativeValueLifecycleScopeRef,
        action: R5RelativeValueLifecycleAction,
        decision_ref: R5RelativeValuePromotionRef,
        rollback_target_ref: R5RelativeValuePromotionRef | None,
    ) -> R5RelativeValueLifecycleAuthorizationEvidence | None:
        persisted = self._repository.get_exact_lifecycle_authorization(
            authorization_ref=authorization_ref,
            scope_ref=scope_ref,
            action=action,
            decision_ref=decision_ref,
            rollback_target_ref=rollback_target_ref,
        )
        if persisted is not None:
            return persisted
        evidence = self._source.get_exact(
            authorization_ref=authorization_ref,
            scope_ref=scope_ref,
            action=action,
            decision_ref=decision_ref,
            rollback_target_ref=rollback_target_ref,
        )
        if evidence is None:
            return None
        try:
            if (
                (evidence.evidence_id, evidence.evidence_version)
                != (authorization_ref.stable_id, authorization_ref.version)
                or evidence.authorization.scope.scope_id != scope_ref.scope_id
                or evidence.content_hash != r5_relative_value_lifecycle_evidence_hash(evidence)
            ):
                raise ValueError("lifecycle authorization source substitution")
        except (AttributeError, TypeError, ValueError) as error:
            raise R5PromotionRepositoryConflict(
                "lifecycle authorization source returned noncanonical evidence"
            ) from error
        return evidence


@dataclass(frozen=True)
class DjangoR5PromotionRuntime:
    """Research-only persistence and exact PIT lifecycle runtime."""

    register_artifact: RegisterR5PromotionArtifact
    evaluate: EvaluateR5RelativeValuePromotion
    apply_lifecycle: ApplyR5RelativeValuePromotionLifecycle
    get_active: GetActiveR5RelativeValuePromotion
    policy_provider: ExactR5RelativeValuePromotionPolicyProvider
    trial_provider: ExactR5RelativeValuePromotionTrialProvider


def build_django_r5_promotion_runtime(
    *,
    artifact_source: ExactR5PromotionArtifactSource,
    owner_record_provider: ExactR5RelativeValueOwnerRecordProvider,
    portfolio_outcome_provider: ExactR5PortfolioOutcomeProvider,
    decision_authorization_source: ExactR5RelativeValueDecisionAuthorizationProvider,
    lifecycle_authorization_source: ExactR5RelativeValueLifecycleAuthorizationProvider,
    clock: R5PromotionServerClock | None = None,
    using: str = "default",
) -> DjangoR5PromotionRuntime:
    """Wire five append-only ledgers to exact owner Application ports."""

    server_clock = clock or DjangoR5PromotionServerClock()
    repository = DjangoR5PromotionRepository(clock=server_clock, using=using)
    keys = {
        repository.unit_of_work_key,
        artifact_source.unit_of_work_key,
        owner_record_provider.unit_of_work_key,
        portfolio_outcome_provider.unit_of_work_key,
        decision_authorization_source.unit_of_work_key,
        lifecycle_authorization_source.unit_of_work_key,
    }
    if len(keys) != 1:
        raise ValueError("R5 promotion owners must share one transaction boundary")
    policy_provider = DjangoR5PromotionPolicyProvider(repository)
    trial_provider = DjangoR5PromotionTrialProvider(repository)
    persisted_decision_authorization = DjangoR5DecisionAuthorizationProvider(repository)
    decision_authorization = _HybridDecisionAuthorizationProvider(
        persisted=persisted_decision_authorization,
        source=decision_authorization_source,
    )
    lifecycle_authorization = _HybridLifecycleAuthorizationProvider(
        repository=repository,
        source=lifecycle_authorization_source,
    )

    def reread_trial_owners(
        trial: R5RelativeValuePromotionTrial,
        *,
        as_of: datetime,
    ) -> None:
        for observation in trial.observations:
            expected_record = observation.fixed_income_record
            bundle = owner_record_provider.get_exact(
                result_id=expected_record.result_id,
                result_version=expected_record.result_version,
                expected_record_hash=expected_record.result_record_hash,
                as_of=as_of,
            )
            if bundle is None:
                raise R5PromotionRepositoryConflict("exact FixedIncome trial record is unavailable")
            try:
                actual_record = project_r5_relative_value_owner_record(bundle)
            except (AttributeError, TypeError, ValueError) as error:
                raise R5PromotionRepositoryConflict(
                    "FixedIncome trial owner record is noncanonical"
                ) from error
            if actual_record != expected_record:
                raise R5PromotionRepositoryConflict(
                    "FixedIncome trial owner record was substituted"
                )
            expected_outcome = observation.portfolio_outcome
            actual_outcome = portfolio_outcome_provider.get_exact(
                outcome_ref=R5RelativeValuePromotionRef(
                    expected_outcome.outcome_id,
                    expected_outcome.outcome_version,
                ),
                expected_owner_record_hash=expected_outcome.owner_record_hash,
                as_of=as_of,
            )
            if actual_outcome != expected_outcome or not expected_outcome.is_active_at(as_of):
                raise R5PromotionRepositoryConflict(
                    "Portfolio trial outcome is unavailable or substituted"
                )

    class ClosureBoundArtifactWriter:
        """Reread every owner using only an ID/version registration command."""

        __slots__ = ()

        def register(
            self,
            command: RegisterR5PromotionArtifactCommand,
        ) -> R5PromotionArtifact:
            with repository.atomic():
                as_of = repository.server_now()
                artifact = artifact_source.get_exact(
                    artifact_kind=command.artifact_kind,
                    artifact_ref=command.artifact_ref,
                    as_of=as_of,
                )
                if artifact is None:
                    raise R5PromotionRepositoryConflict(
                        "exact Research promotion artifact is unavailable"
                    )
                try:
                    canonical = decode_r5_promotion_artifact(encode_r5_promotion_artifact(artifact))
                except (AttributeError, TypeError, ValueError) as error:
                    raise R5PromotionRepositoryConflict(
                        "Research artifact source is noncanonical"
                    ) from error
                expected_type = (
                    R5RelativeValuePromotionPolicy
                    if command.artifact_kind is R5PromotionArtifactKind.POLICY
                    else R5RelativeValuePromotionTrial
                )
                if isinstance(canonical, R5RelativeValuePromotionPolicy):
                    actual_ref = R5RelativeValuePromotionRef(
                        canonical.policy_id,
                        canonical.policy_version,
                    )
                else:
                    actual_ref = R5RelativeValuePromotionRef(
                        canonical.trial_id,
                        canonical.trial_version,
                    )
                if (
                    type(canonical) is not expected_type
                    or canonical != artifact
                    or actual_ref != command.artifact_ref
                    or not canonical.is_active_at(as_of)
                ):
                    raise R5PromotionRepositoryConflict(
                        "Research artifact kind, identity or active window differs"
                    )
                if type(canonical) is R5RelativeValuePromotionTrial:
                    trial = canonical
                    policy = policy_provider.get_exact(
                        R5RelativeValuePromotionRef(
                            trial.policy_id,
                            trial.policy_version,
                        ),
                        as_of=as_of,
                    )
                    if (
                        policy is None
                        or policy.content_hash != trial.policy_content_hash
                        or policy.scope != trial.scope
                    ):
                        raise R5PromotionRepositoryConflict(
                            "trial policy is unavailable or substituted"
                        )
                    reread_trial_owners(trial, as_of=as_of)
                return repository._append_artifact(canonical)

    evaluate = EvaluateR5RelativeValuePromotion(
        policy_provider=policy_provider,
        trial_provider=trial_provider,
        owner_record_provider=owner_record_provider,
        portfolio_outcome_provider=portfolio_outcome_provider,
        authorization_provider=decision_authorization,
        repository=repository,
    )
    apply_lifecycle = ApplyR5RelativeValuePromotionLifecycle(
        policy_provider=policy_provider,
        trial_provider=trial_provider,
        owner_record_provider=owner_record_provider,
        portfolio_outcome_provider=portfolio_outcome_provider,
        decision_authorization_provider=persisted_decision_authorization,
        lifecycle_authorization_provider=lifecycle_authorization,
        repository=repository,
    )
    get_active = GetActiveR5RelativeValuePromotion(
        policy_provider=policy_provider,
        trial_provider=trial_provider,
        owner_record_provider=owner_record_provider,
        portfolio_outcome_provider=portfolio_outcome_provider,
        decision_authorization_provider=persisted_decision_authorization,
        repository=repository,
        clock=server_clock,
    )
    return DjangoR5PromotionRuntime(
        register_artifact=RegisterR5PromotionArtifact(
            writer=ClosureBoundArtifactWriter(),
        ),
        evaluate=evaluate,
        apply_lifecycle=apply_lifecycle,
        get_active=get_active,
        policy_provider=policy_provider,
        trial_provider=trial_provider,
    )


__all__ = [
    "DjangoR5PromotionRuntime",
    "build_django_r5_promotion_runtime",
]
