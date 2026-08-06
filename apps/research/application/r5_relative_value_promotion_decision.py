"""ID-only orchestration for exact R5 relative-value promotion decisions."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypedDict

from apps.fixed_income.application.relative_value_persistence import (
    R5PersistedRelativeValueBundle,
)
from apps.fixed_income.domain.evidence import (
    canonical_hash,
    require_aware,
    require_sha256,
    require_token,
)
from apps.research.application.r5_relative_value_promotion_projection import (
    project_r5_relative_value_owner_record,
)
from apps.research.domain.r5_relative_value_portfolio_outcome import (
    R5PortfolioOutcomeSeal,
)
from apps.research.domain.r5_relative_value_promotion_decision import (
    R5RelativeValuePromotionDecision,
    create_r5_relative_value_promotion_decision,
    r5_relative_value_promotion_decision_valid_until,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
)


@dataclass(frozen=True)
class R5RelativeValuePromotionRef:
    """ID/version-only immutable owner-artifact reference."""

    stable_id: str
    version: str

    def __post_init__(self) -> None:
        require_token(self.stable_id, "R5 promotion stable_id", maximum=300)
        require_token(self.version, "R5 promotion version")


class _DecisionAuthorizationValues(TypedDict):
    authorization_version: str
    scope_id: str
    scope_content_hash: str
    policy_ref: R5RelativeValuePromotionRef
    trial_ref: R5RelativeValuePromotionRef
    issued_at: datetime
    recorded_at: datetime
    decided_at: datetime
    decision_recorded_at: datetime
    decision_valid_until: datetime
    valid_until: datetime


@dataclass(frozen=True)
class R5RelativeValueDecisionAuthorization:
    """Research-owner permission and stable server receipt for evaluation."""

    authorization_id: str
    authorization_version: str
    owner: str
    capability: str
    purpose: str
    scope_id: str
    scope_content_hash: str
    policy_ref: R5RelativeValuePromotionRef
    trial_ref: R5RelativeValuePromotionRef
    issued_at: datetime
    recorded_at: datetime
    decided_at: datetime
    decision_recorded_at: datetime
    decision_valid_until: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        authorization_version: str,
        scope_id: str,
        scope_content_hash: str,
        policy_ref: R5RelativeValuePromotionRef,
        trial_ref: R5RelativeValuePromotionRef,
        issued_at: datetime,
        recorded_at: datetime,
        decided_at: datetime,
        decision_recorded_at: datetime,
        decision_valid_until: datetime,
        valid_until: datetime,
    ) -> R5RelativeValueDecisionAuthorization:
        """Seal exact evaluation authority without an outcome or caller hash."""

        values: _DecisionAuthorizationValues = {
            "authorization_version": authorization_version,
            "scope_id": scope_id,
            "scope_content_hash": scope_content_hash,
            "policy_ref": policy_ref,
            "trial_ref": trial_ref,
            "issued_at": issued_at,
            "recorded_at": recorded_at,
            "decided_at": decided_at,
            "decision_recorded_at": decision_recorded_at,
            "decision_valid_until": decision_valid_until,
            "valid_until": valid_until,
        }
        digest = canonical_hash(_authorization_payload(**values))
        return cls(
            authorization_id=f"r5-rv-decision-auth:{digest}",
            owner="research",
            capability="r5",
            purpose="fixed_income_relative_value_research",
            content_hash=digest,
            **values,
        )

    def __post_init__(self) -> None:
        require_token(self.authorization_version, "R5 decision authorization version")
        if (
            self.owner != "research"
            or self.capability != "r5"
            or self.purpose != "fixed_income_relative_value_research"
        ):
            raise ValueError("R5 decision authorization authority is invalid")
        require_token(self.scope_id, "R5 decision authorization scope_id", maximum=300)
        require_sha256(
            self.scope_content_hash,
            "R5 decision authorization scope_content_hash",
        )
        for field_name in (
            "issued_at",
            "recorded_at",
            "decided_at",
            "decision_recorded_at",
            "decision_valid_until",
            "valid_until",
        ):
            require_aware(
                getattr(self, field_name),
                f"R5 decision authorization {field_name}",
            )
        if not (
            self.issued_at
            <= self.recorded_at
            <= self.decided_at
            <= self.decision_recorded_at
            < self.decision_valid_until
            <= self.valid_until
        ):
            raise ValueError("R5 decision authorization clocks are invalid")
        require_sha256(self.content_hash, "R5 decision authorization content_hash")
        expected = r5_relative_value_decision_authorization_hash(self)
        if (
            self.content_hash != expected
            or self.authorization_id != f"r5-rv-decision-auth:{expected}"
        ):
            raise ValueError("R5 decision authorization content hash or identity mismatch")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the authorization receipt is known and active."""

        require_aware(as_of, "R5 decision authorization as_of")
        return self.recorded_at <= as_of < self.valid_until


def _authorization_payload(
    *,
    authorization_version: str,
    scope_id: str,
    scope_content_hash: str,
    policy_ref: R5RelativeValuePromotionRef,
    trial_ref: R5RelativeValuePromotionRef,
    issued_at: datetime,
    recorded_at: datetime,
    decided_at: datetime,
    decision_recorded_at: datetime,
    decision_valid_until: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-decision-authorization.v1",
        "identity": (
            authorization_version,
            "research",
            "r5",
            "fixed_income_relative_value_research",
        ),
        "scope": (scope_id, scope_content_hash),
        "policy": (policy_ref.stable_id, policy_ref.version),
        "trial": (trial_ref.stable_id, trial_ref.version),
        "window": (
            issued_at,
            recorded_at,
            decided_at,
            decision_recorded_at,
            decision_valid_until,
            valid_until,
        ),
    }


def r5_relative_value_decision_authorization_hash(
    authorization: R5RelativeValueDecisionAuthorization,
) -> str:
    """Recompute one exact Research decision authorization hash."""

    return canonical_hash(
        _authorization_payload(
            authorization_version=authorization.authorization_version,
            scope_id=authorization.scope_id,
            scope_content_hash=authorization.scope_content_hash,
            policy_ref=authorization.policy_ref,
            trial_ref=authorization.trial_ref,
            issued_at=authorization.issued_at,
            recorded_at=authorization.recorded_at,
            decided_at=authorization.decided_at,
            decision_recorded_at=authorization.decision_recorded_at,
            decision_valid_until=authorization.decision_valid_until,
            valid_until=authorization.valid_until,
        )
    )


@dataclass(frozen=True)
class R5RelativeValuePromotionDecisionBundle:
    """Atomic derived decision plus its exact Research authorization receipt."""

    decision: R5RelativeValuePromotionDecision
    authorization: R5RelativeValueDecisionAuthorization
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        decision: R5RelativeValuePromotionDecision,
        authorization: R5RelativeValueDecisionAuthorization,
    ) -> R5RelativeValuePromotionDecisionBundle:
        """Seal one append-only decision persistence unit."""

        digest = _decision_bundle_hash(decision, authorization)
        return cls(
            decision=decision,
            authorization=authorization,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if (
            self.authorization.scope_id != self.decision.scope.scope_id
            or self.authorization.scope_content_hash != self.decision.scope.content_hash
            or self.authorization.policy_ref
            != R5RelativeValuePromotionRef(
                self.decision.policy.policy_id,
                self.decision.policy.policy_version,
            )
            or self.authorization.trial_ref
            != R5RelativeValuePromotionRef(
                self.decision.trial.trial_id,
                self.decision.trial.trial_version,
            )
            or self.authorization.decision_recorded_at != self.decision.recorded_at
            or self.authorization.decided_at != self.decision.decided_at
            or self.authorization.decision_valid_until != self.decision.valid_until
            or not self.authorization.is_active_at(self.decision.decided_at)
        ):
            raise ValueError("R5 promotion decision authorization was substituted")
        require_sha256(self.content_hash, "R5 decision bundle content_hash")
        if self.content_hash != _decision_bundle_hash(
            self.decision,
            self.authorization,
        ):
            raise ValueError("R5 promotion decision bundle content hash mismatch")


def _decision_bundle_hash(
    decision: R5RelativeValuePromotionDecision,
    authorization: R5RelativeValueDecisionAuthorization,
) -> str:
    return canonical_hash(
        {
            "schema": "research-r5-relative-value-promotion-decision-bundle.v1",
            "decision": (
                decision.decision_id,
                decision.decision_version,
                decision.content_hash,
            ),
            "authorization": (
                authorization.authorization_id,
                authorization.authorization_version,
                authorization.content_hash,
            ),
        }
    )


class ExactR5RelativeValuePromotionPolicyProvider(Protocol):
    """Read one exact content-addressed Research policy."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary."""

    def get_exact(
        self,
        policy_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionPolicy | None:
        """Return only the exact active policy receipt."""


class ExactR5RelativeValuePromotionTrialProvider(Protocol):
    """Read one exact Research-owned true trial seal."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary."""

    def get_exact(
        self,
        trial_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionTrial | None:
        """Return only the exact active trial receipt."""


class ExactR5RelativeValueOwnerRecordProvider(Protocol):
    """Reread one exact persisted fixed-income owner bundle."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary."""

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R5PersistedRelativeValueBundle | None:
        """Return one strict hash-bound audit record known at ``as_of``."""


class ExactR5PortfolioOutcomeProvider(Protocol):
    """Reread one exact canonical Portfolio outcome owner record."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary."""

    def get_exact(
        self,
        *,
        outcome_ref: R5RelativeValuePromotionRef,
        expected_owner_record_hash: str,
        as_of: datetime,
    ) -> R5PortfolioOutcomeSeal | None:
        """Return only the exact hash-bound Portfolio owner projection."""


class ExactR5RelativeValueDecisionAuthorizationProvider(Protocol):
    """Read independently owned evaluation authority for exact inputs."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary."""

    def get_exact(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        policy_ref: R5RelativeValuePromotionRef,
        trial_ref: R5RelativeValuePromotionRef,
        as_of: datetime,
    ) -> R5RelativeValueDecisionAuthorization | None:
        """Return exact owner evidence without minting from caller values."""


class R5RelativeValuePromotionDecisionRepository(Protocol):
    """Append-only Phase-A port for exact R5 decision bundles."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary."""

    def atomic(self) -> AbstractContextManager[None]:
        """Wrap all dynamic rereads and the append atomically."""

    def append_decision_bundle(
        self,
        bundle: R5RelativeValuePromotionDecisionBundle,
    ) -> R5RelativeValuePromotionDecisionBundle:
        """Append or return only an exact idempotent winner."""

    def get_decision_bundle(
        self,
        decision_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionDecisionBundle | None:
        """Return one exact decision bundle known at knowledge time."""


@dataclass(frozen=True)
class EvaluateR5RelativeValuePromotionCommand:
    """ID-only request carrying no hashes, evidence, metrics or decision."""

    policy_ref: R5RelativeValuePromotionRef
    trial_ref: R5RelativeValuePromotionRef
    authorization_ref: R5RelativeValuePromotionRef
    as_of: datetime

    def __post_init__(self) -> None:
        require_aware(self.as_of, "R5 promotion command as_of")


class R5RelativeValuePromotionEvidenceError(ValueError):
    """Stable fail-closed result for missing or substituted owner evidence."""

    def __init__(self, reason_code: str, detail: str) -> None:
        require_token(reason_code, "R5 promotion evidence reason_code", maximum=200)
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code


class EvaluateR5RelativeValuePromotion:
    """Dynamically reread policy, trial, every result and authorization."""

    def __init__(
        self,
        *,
        policy_provider: ExactR5RelativeValuePromotionPolicyProvider,
        trial_provider: ExactR5RelativeValuePromotionTrialProvider,
        owner_record_provider: ExactR5RelativeValueOwnerRecordProvider,
        portfolio_outcome_provider: ExactR5PortfolioOutcomeProvider,
        authorization_provider: ExactR5RelativeValueDecisionAuthorizationProvider,
        repository: R5RelativeValuePromotionDecisionRepository,
    ) -> None:
        self._policy_provider = policy_provider
        self._trial_provider = trial_provider
        self._owner_record_provider = owner_record_provider
        self._portfolio_outcome_provider = portfolio_outcome_provider
        self._authorization_provider = authorization_provider
        self._repository = repository
        keys = {
            policy_provider.unit_of_work_key,
            trial_provider.unit_of_work_key,
            owner_record_provider.unit_of_work_key,
            portfolio_outcome_provider.unit_of_work_key,
            authorization_provider.unit_of_work_key,
            repository.unit_of_work_key,
        }
        if len(keys) != 1:
            raise ValueError("R5 promotion dynamic owners use different units of work")

    def execute(
        self,
        command: EvaluateR5RelativeValuePromotionCommand,
    ) -> R5RelativeValuePromotionDecision:
        """Resolve exact owner inputs, derive a decision and append atomically."""

        with self._repository.atomic():
            policy = self._load_policy(command)
            trial = self._load_trial(command, policy)
            self._reread_fixed_income_records(trial, as_of=command.as_of)
            self._reread_portfolio_outcomes(trial, as_of=command.as_of)
            authorization = self._load_authorization(command, policy, trial)
            decision = create_r5_relative_value_promotion_decision(
                policy=policy,
                trial=trial,
                decided_at=command.as_of,
                recorded_at=authorization.decision_recorded_at,
            )
            bundle = R5RelativeValuePromotionDecisionBundle.create(
                decision=decision,
                authorization=authorization,
            )
            persisted = self._repository.append_decision_bundle(bundle)
            if persisted != bundle:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_promotion.repository_conflict",
                    "repository changed the exact decision bundle",
                )
            return persisted.decision

    def _load_policy(
        self,
        command: EvaluateR5RelativeValuePromotionCommand,
    ) -> R5RelativeValuePromotionPolicy:
        policy = self._policy_provider.get_exact(
            command.policy_ref,
            as_of=command.as_of,
        )
        if policy is None:
            raise R5RelativeValuePromotionEvidenceError(
                "r5_promotion.policy_missing",
                "exact Research policy is unavailable",
            )
        if (policy.policy_id, policy.policy_version) != (
            command.policy_ref.stable_id,
            command.policy_ref.version,
        ) or not policy.is_active_at(command.as_of):
            raise R5RelativeValuePromotionEvidenceError(
                "r5_promotion.evidence_substituted",
                "Research policy identity or active window differs",
            )
        return policy

    def _load_trial(
        self,
        command: EvaluateR5RelativeValuePromotionCommand,
        policy: R5RelativeValuePromotionPolicy,
    ) -> R5RelativeValuePromotionTrial:
        trial = self._trial_provider.get_exact(
            command.trial_ref,
            as_of=command.as_of,
        )
        if trial is None:
            raise R5RelativeValuePromotionEvidenceError(
                "r5_promotion.trial_missing",
                "exact Research trial is unavailable",
            )
        if (
            (trial.trial_id, trial.trial_version)
            != (command.trial_ref.stable_id, command.trial_ref.version)
            or not trial.is_active_at(command.as_of)
            or trial.policy_id != policy.policy_id
            or trial.policy_version != policy.policy_version
            or trial.policy_content_hash != policy.content_hash
            or trial.scope != policy.scope
        ):
            raise R5RelativeValuePromotionEvidenceError(
                "r5_promotion.evidence_substituted",
                "Research trial or policy binding differs",
            )
        return trial

    def _reread_fixed_income_records(
        self,
        trial: R5RelativeValuePromotionTrial,
        *,
        as_of: datetime,
    ) -> None:
        for observation in trial.observations:
            expected = observation.fixed_income_record
            bundle = self._owner_record_provider.get_exact(
                result_id=expected.result_id,
                result_version=expected.result_version,
                expected_record_hash=expected.result_record_hash,
                as_of=as_of,
            )
            if bundle is None:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_promotion.owner_record_missing",
                    "exact fixed_income persisted result is unavailable",
                )
            try:
                actual = project_r5_relative_value_owner_record(bundle)
            except ValueError as error:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_promotion.evidence_substituted",
                    "fixed_income owner bundle is not canonical",
                ) from error
            if actual != expected:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_promotion.evidence_substituted",
                    "fixed_income owner record differs from the trial seal",
                )

    def _reread_portfolio_outcomes(
        self,
        trial: R5RelativeValuePromotionTrial,
        *,
        as_of: datetime,
    ) -> None:
        for observation in trial.observations:
            expected = observation.portfolio_outcome
            actual = self._portfolio_outcome_provider.get_exact(
                outcome_ref=R5RelativeValuePromotionRef(
                    expected.outcome_id,
                    expected.outcome_version,
                ),
                expected_owner_record_hash=expected.owner_record_hash,
                as_of=as_of,
            )
            if actual is None:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_promotion.portfolio_outcome_missing",
                    "exact Portfolio realized outcome is unavailable",
                )
            if actual != expected or not actual.is_active_at(as_of):
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_promotion.evidence_substituted",
                    "Portfolio outcome differs from the Research trial seal",
                )

    def _load_authorization(
        self,
        command: EvaluateR5RelativeValuePromotionCommand,
        policy: R5RelativeValuePromotionPolicy,
        trial: R5RelativeValuePromotionTrial,
    ) -> R5RelativeValueDecisionAuthorization:
        expected_decision_valid_until = r5_relative_value_promotion_decision_valid_until(
            policy=policy,
            trial=trial,
            decided_at=command.as_of,
        )
        authorization = self._authorization_provider.get_exact(
            authorization_ref=command.authorization_ref,
            policy_ref=command.policy_ref,
            trial_ref=command.trial_ref,
            as_of=command.as_of,
        )
        if authorization is None:
            raise R5RelativeValuePromotionEvidenceError(
                "r5_promotion.authorization_missing",
                "exact Research evaluation authorization is unavailable",
            )
        if (
            (authorization.authorization_id, authorization.authorization_version)
            != (
                command.authorization_ref.stable_id,
                command.authorization_ref.version,
            )
            or authorization.policy_ref != command.policy_ref
            or authorization.trial_ref != command.trial_ref
            or authorization.scope_id != policy.scope.scope_id
            or authorization.scope_content_hash != policy.scope.content_hash
            or authorization.decided_at != command.as_of
            or authorization.decision_valid_until != expected_decision_valid_until
            or authorization.decision_valid_until > authorization.valid_until
            or not authorization.is_active_at(command.as_of)
            or authorization.decision_recorded_at >= authorization.decision_valid_until
            or authorization.content_hash
            != r5_relative_value_decision_authorization_hash(authorization)
        ):
            raise R5RelativeValuePromotionEvidenceError(
                "r5_promotion.evidence_substituted",
                "Research evaluation authorization differs",
            )
        return authorization


__all__ = [
    "EvaluateR5RelativeValuePromotion",
    "EvaluateR5RelativeValuePromotionCommand",
    "ExactR5PortfolioOutcomeProvider",
    "ExactR5RelativeValueDecisionAuthorizationProvider",
    "ExactR5RelativeValueOwnerRecordProvider",
    "ExactR5RelativeValuePromotionPolicyProvider",
    "ExactR5RelativeValuePromotionTrialProvider",
    "R5RelativeValueDecisionAuthorization",
    "R5RelativeValuePromotionDecisionBundle",
    "R5RelativeValuePromotionDecisionRepository",
    "R5RelativeValuePromotionEvidenceError",
    "R5RelativeValuePromotionRef",
    "r5_relative_value_decision_authorization_hash",
]
