"""ID-only R5 promotion lifecycle orchestration and PIT active provider."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, TypedDict

from apps.fixed_income.application.relative_value_projection import (
    project_r5_relative_value_owner_record,
)
from apps.fixed_income.domain.evidence import (
    canonical_hash,
    require_aware,
    require_sha256,
    require_token,
)
from apps.research.application.r5_relative_value_promotion_decision import (
    ExactR5PortfolioOutcomeProvider,
    ExactR5RelativeValueDecisionAuthorizationProvider,
    ExactR5RelativeValueOwnerRecordProvider,
    ExactR5RelativeValuePromotionPolicyProvider,
    ExactR5RelativeValuePromotionTrialProvider,
    R5RelativeValuePromotionDecisionBundle,
    R5RelativeValuePromotionEvidenceError,
    R5RelativeValuePromotionRef,
)
from apps.research.application.r5_relative_value_promotion_persistence import (
    R5PromotionServerClock,
    require_r5_promotion_pit_cutoff,
)
from apps.research.domain.r5_relative_value_promotion_decision import (
    R5RelativeValuePromotionDecision,
    R5RelativeValuePromotionDecisionOutcome,
    create_r5_relative_value_promotion_decision,
)
from apps.research.domain.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueDecisionIdentity,
    R5RelativeValueLifecycleAuthorization,
    R5RelativeValueLifecycleEvent,
    R5RelativeValueLifecycleEventType,
    create_r5_relative_value_lifecycle_event,
    create_r5_relative_value_lifecycle_root,
    derive_r5_relative_value_lifecycle_state,
    r5_relative_value_lifecycle_reason_hash,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
)


@dataclass(frozen=True)
class R5RelativeValueLifecycleScopeRef:
    """Caller-safe semantic scope reference carrying no owner hash."""

    scope_id: str

    def __post_init__(self) -> None:
        require_token(self.scope_id, "R5 lifecycle scope_id", maximum=300)


class R5RelativeValueLifecycleAction(str, Enum):
    """Caller-selectable lifecycle action without outcome authority."""

    PROMOTE = "promote"
    RETIRE = "retire"
    ROLLBACK = "rollback"


def _event_type(
    action: R5RelativeValueLifecycleAction,
) -> R5RelativeValueLifecycleEventType:
    if action is R5RelativeValueLifecycleAction.PROMOTE:
        return R5RelativeValueLifecycleEventType.PROMOTED
    if action is R5RelativeValueLifecycleAction.RETIRE:
        return R5RelativeValueLifecycleEventType.RETIRED
    return R5RelativeValueLifecycleEventType.ROLLED_BACK


class _LifecycleEvidenceValues(TypedDict):
    evidence_version: str
    authorization: R5RelativeValueLifecycleAuthorization
    reason_codes: tuple[str, ...]
    receipt_recorded_at: datetime
    occurred_at: datetime
    event_recorded_at: datetime
    event_ref: R5RelativeValuePromotionRef
    event_content_hash: str


@dataclass(frozen=True)
class R5RelativeValueLifecycleAuthorizationEvidence:
    """Owner receipt binding authorization to one exact output event."""

    evidence_id: str
    evidence_version: str
    authorization: R5RelativeValueLifecycleAuthorization
    reason_codes: tuple[str, ...]
    receipt_recorded_at: datetime
    occurred_at: datetime
    event_recorded_at: datetime
    event_ref: R5RelativeValuePromotionRef
    event_content_hash: str
    content_hash: str

    @classmethod
    def from_event(
        cls,
        *,
        evidence_version: str,
        event: R5RelativeValueLifecycleEvent,
        receipt_recorded_at: datetime,
    ) -> R5RelativeValueLifecycleAuthorizationEvidence:
        """Create an independent receipt for an already deterministic event."""

        values: _LifecycleEvidenceValues = {
            "evidence_version": evidence_version,
            "authorization": event.authorization,
            "reason_codes": event.reason_codes,
            "receipt_recorded_at": receipt_recorded_at,
            "occurred_at": event.occurred_at,
            "event_recorded_at": event.recorded_at,
            "event_ref": R5RelativeValuePromotionRef(
                event.event_id,
                event.event_version,
            ),
            "event_content_hash": event.content_hash,
        }
        digest = canonical_hash(_lifecycle_evidence_payload(**values))
        return cls(
            evidence_id=f"r5-rv-lifecycle-evidence:{digest}",
            content_hash=digest,
            **values,
        )

    def __post_init__(self) -> None:
        require_token(self.evidence_version, "R5 lifecycle evidence version")
        if (
            not self.reason_codes
            or self.reason_codes != tuple(sorted(set(self.reason_codes)))
            or self.authorization.reason_hash
            != r5_relative_value_lifecycle_reason_hash(self.reason_codes)
        ):
            raise ValueError("R5 lifecycle evidence reasons were substituted")
        for field_name in (
            "receipt_recorded_at",
            "occurred_at",
            "event_recorded_at",
        ):
            require_aware(
                getattr(self, field_name),
                f"R5 lifecycle evidence {field_name}",
            )
        if not (
            self.authorization.recorded_at
            <= self.receipt_recorded_at
            <= self.occurred_at
            <= self.event_recorded_at
            and self.occurred_at < self.authorization.valid_until
        ):
            raise ValueError("R5 lifecycle evidence clocks are invalid")
        require_sha256(
            self.event_content_hash,
            "R5 lifecycle evidence event_content_hash",
        )
        require_sha256(self.content_hash, "R5 lifecycle evidence content_hash")
        expected = r5_relative_value_lifecycle_evidence_hash(self)
        if (
            self.content_hash != expected
            or self.evidence_id != f"r5-rv-lifecycle-evidence:{expected}"
        ):
            raise ValueError("R5 lifecycle evidence content hash or identity mismatch")


def _lifecycle_evidence_payload(
    *,
    evidence_version: str,
    authorization: R5RelativeValueLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    receipt_recorded_at: datetime,
    occurred_at: datetime,
    event_recorded_at: datetime,
    event_ref: R5RelativeValuePromotionRef,
    event_content_hash: str,
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-lifecycle-evidence.v1",
        "evidence_version": evidence_version,
        "authorization": (
            authorization.authorization_id,
            authorization.authorization_version,
            authorization.content_hash,
        ),
        "reason_codes": reason_codes,
        "window": (receipt_recorded_at, occurred_at, event_recorded_at),
        "event": (
            event_ref.stable_id,
            event_ref.version,
            event_content_hash,
        ),
    }


def r5_relative_value_lifecycle_evidence_hash(
    evidence: R5RelativeValueLifecycleAuthorizationEvidence,
) -> str:
    """Recompute one complete exact lifecycle authorization receipt."""

    return canonical_hash(
        _lifecycle_evidence_payload(
            evidence_version=evidence.evidence_version,
            authorization=evidence.authorization,
            reason_codes=evidence.reason_codes,
            receipt_recorded_at=evidence.receipt_recorded_at,
            occurred_at=evidence.occurred_at,
            event_recorded_at=evidence.event_recorded_at,
            event_ref=evidence.event_ref,
            event_content_hash=evidence.event_content_hash,
        )
    )


@dataclass(frozen=True)
class R5RelativeValueLifecycleEventBundle:
    """Atomic lifecycle event plus its independent owner receipt."""

    event: R5RelativeValueLifecycleEvent
    authorization_evidence: R5RelativeValueLifecycleAuthorizationEvidence
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        event: R5RelativeValueLifecycleEvent,
        authorization_evidence: R5RelativeValueLifecycleAuthorizationEvidence,
    ) -> R5RelativeValueLifecycleEventBundle:
        """Seal an exact lifecycle persistence unit."""

        digest = _lifecycle_event_bundle_hash(event, authorization_evidence)
        return cls(
            event=event,
            authorization_evidence=authorization_evidence,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        evidence = self.authorization_evidence
        if (
            evidence.authorization != self.event.authorization
            or evidence.reason_codes != self.event.reason_codes
            or evidence.occurred_at != self.event.occurred_at
            or evidence.event_recorded_at != self.event.recorded_at
            or evidence.event_ref
            != R5RelativeValuePromotionRef(
                self.event.event_id,
                self.event.event_version,
            )
            or evidence.event_content_hash != self.event.content_hash
        ):
            raise ValueError("R5 lifecycle evidence does not bind the exact event")
        require_sha256(self.content_hash, "R5 lifecycle event bundle content_hash")
        if self.content_hash != _lifecycle_event_bundle_hash(self.event, evidence):
            raise ValueError("R5 lifecycle event bundle content hash mismatch")


def _lifecycle_event_bundle_hash(
    event: R5RelativeValueLifecycleEvent,
    evidence: R5RelativeValueLifecycleAuthorizationEvidence,
) -> str:
    return canonical_hash(
        {
            "schema": "research-r5-relative-value-lifecycle-event-bundle.v1",
            "event": (event.event_id, event.event_version, event.content_hash),
            "evidence": (
                evidence.evidence_id,
                evidence.evidence_version,
                evidence.content_hash,
            ),
        }
    )


class ExactR5RelativeValueLifecycleAuthorizationProvider(Protocol):
    """Read independently recorded authority for one ID-only action."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary."""

    def get_exact(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        scope_ref: R5RelativeValueLifecycleScopeRef,
        action: R5RelativeValueLifecycleAction,
        decision_ref: R5RelativeValuePromotionRef,
        rollback_target_ref: R5RelativeValuePromotionRef | None,
    ) -> R5RelativeValueLifecycleAuthorizationEvidence | None:
        """Return exact evidence without accepting caller clocks or reasons."""


class R5RelativeValuePromotionLifecycleRepository(Protocol):
    """Append-only shared-UoW repository for decisions and lifecycle events."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary."""

    def atomic(self) -> AbstractContextManager[None]:
        """Wrap all owner rereads, replay and append atomically."""

    def get_decision_bundle(
        self,
        decision_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionDecisionBundle | None:
        """Return one exact decision bundle known at knowledge time."""

    def load_lifecycle_stream(
        self,
        scope_ref: R5RelativeValueLifecycleScopeRef,
    ) -> tuple[R5RelativeValueLifecycleEventBundle, ...]:
        """Return the complete ordered stream, never a caller-selected suffix."""

    def get_event_bundle_by_authorization(
        self,
        authorization_ref: R5RelativeValuePromotionRef,
    ) -> R5RelativeValueLifecycleEventBundle | None:
        """Return an exact idempotent winner for one evidence receipt."""

    def append_lifecycle_event_bundle(
        self,
        bundle: R5RelativeValueLifecycleEventBundle,
    ) -> R5RelativeValueLifecycleEventBundle:
        """Append or return only the exact authorization winner."""


@dataclass(frozen=True)
class ApplyR5RelativeValueLifecycleCommand:
    """ID-only command carrying no hash, object, clock, reason or output ID."""

    scope_ref: R5RelativeValueLifecycleScopeRef
    action: R5RelativeValueLifecycleAction
    decision_ref: R5RelativeValuePromotionRef
    authorization_ref: R5RelativeValuePromotionRef
    rollback_target_ref: R5RelativeValuePromotionRef | None = None

    def __post_init__(self) -> None:
        if (self.action is R5RelativeValueLifecycleAction.ROLLBACK) != (
            self.rollback_target_ref is not None
        ):
            raise ValueError("R5 rollback alone requires one target reference")


class _R5DecisionOwnerGraphReader:
    def __init__(
        self,
        *,
        policy_provider: ExactR5RelativeValuePromotionPolicyProvider,
        trial_provider: ExactR5RelativeValuePromotionTrialProvider,
        owner_record_provider: ExactR5RelativeValueOwnerRecordProvider,
        portfolio_outcome_provider: ExactR5PortfolioOutcomeProvider,
        decision_authorization_provider: ExactR5RelativeValueDecisionAuthorizationProvider,
        repository: R5RelativeValuePromotionLifecycleRepository,
    ) -> None:
        self._policy_provider = policy_provider
        self._trial_provider = trial_provider
        self._owner_record_provider = owner_record_provider
        self._portfolio_outcome_provider = portfolio_outcome_provider
        self._decision_authorization_provider = decision_authorization_provider
        self._repository = repository
        keys = {
            policy_provider.unit_of_work_key,
            trial_provider.unit_of_work_key,
            owner_record_provider.unit_of_work_key,
            portfolio_outcome_provider.unit_of_work_key,
            decision_authorization_provider.unit_of_work_key,
            repository.unit_of_work_key,
        }
        if len(keys) != 1:
            raise ValueError("R5 lifecycle dynamic owners use different units of work")

    def load(
        self,
        decision_ref: R5RelativeValuePromotionRef,
        *,
        knowledge_as_of: datetime,
        require_current: bool,
    ) -> R5RelativeValuePromotionDecisionBundle:
        require_aware(knowledge_as_of, "R5 lifecycle decision knowledge_as_of")
        bundle = self._repository.get_decision_bundle(
            decision_ref,
            as_of=knowledge_as_of,
        )
        if bundle is None:
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.decision_missing",
                "exact R5 promotion decision is unavailable",
            )
        decision = bundle.decision
        if (
            (decision.decision_id, decision.decision_version)
            != (decision_ref.stable_id, decision_ref.version)
            or decision.outcome is not R5RelativeValuePromotionDecisionOutcome.APPROVED
            or decision.recorded_at > knowledge_as_of
            or (
                require_current
                and not decision.recorded_at <= knowledge_as_of < decision.valid_until
            )
            or not (
                decision.research_only
                and decision.must_not_use_for_decision
                and decision.must_not_execute
            )
        ):
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.decision_invalid",
                "decision identity, outcome, window or safety boundary differs",
            )
        owner_as_of = knowledge_as_of if require_current else decision.decided_at
        policy_ref = R5RelativeValuePromotionRef(
            decision.policy.policy_id,
            decision.policy.policy_version,
        )
        policy = self._policy_provider.get_exact(policy_ref, as_of=owner_as_of)
        if policy is None:
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.policy_missing",
                "exact Research policy is unavailable",
            )
        trial_ref = R5RelativeValuePromotionRef(
            decision.trial.trial_id,
            decision.trial.trial_version,
        )
        trial = self._trial_provider.get_exact(trial_ref, as_of=owner_as_of)
        if trial is None:
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.trial_missing",
                "exact Research trial is unavailable",
            )
        if (
            policy != decision.policy
            or trial != decision.trial
            or not policy.is_active_at(owner_as_of)
            or not trial.is_active_at(owner_as_of)
            or not (
                policy.research_only
                and policy.must_not_use_for_decision
                and policy.must_not_execute
                and trial.research_only
                and trial.must_not_use_for_decision
                and trial.must_not_execute
            )
        ):
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.evidence_substituted",
                "Research policy or trial differs from the decision",
            )
        self._reread_owner_records(trial, as_of=owner_as_of)
        authorization = self._decision_authorization_provider.get_exact(
            authorization_ref=R5RelativeValuePromotionRef(
                bundle.authorization.authorization_id,
                bundle.authorization.authorization_version,
            ),
            policy_ref=policy_ref,
            trial_ref=trial_ref,
            as_of=owner_as_of,
        )
        if authorization is None:
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.decision_authorization_missing",
                "exact decision authorization is unavailable",
            )
        if authorization != bundle.authorization or not authorization.is_active_at(owner_as_of):
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.evidence_substituted",
                "decision authorization differs from the persisted bundle",
            )
        try:
            rebuilt_decision = create_r5_relative_value_promotion_decision(
                policy=policy,
                trial=trial,
                decided_at=decision.decided_at,
                recorded_at=decision.recorded_at,
            )
            rebuilt_bundle = R5RelativeValuePromotionDecisionBundle.create(
                decision=rebuilt_decision,
                authorization=authorization,
            )
        except ValueError as error:
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.evidence_substituted",
                "decision owner graph is not canonical",
            ) from error
        if rebuilt_bundle != bundle:
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.evidence_substituted",
                "decision bundle cannot be reproduced from exact owners",
            )
        return bundle

    def _reread_owner_records(
        self,
        trial: R5RelativeValuePromotionTrial,
        *,
        as_of: datetime,
    ) -> None:
        for observation in trial.observations:
            expected_record = observation.fixed_income_record
            persisted = self._owner_record_provider.get_exact(
                result_id=expected_record.result_id,
                result_version=expected_record.result_version,
                expected_record_hash=expected_record.result_record_hash,
                as_of=as_of,
            )
            if persisted is None:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_lifecycle.owner_record_missing",
                    "exact fixed_income result is unavailable",
                )
            try:
                actual_record = project_r5_relative_value_owner_record(persisted)
            except ValueError as error:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_lifecycle.evidence_substituted",
                    "fixed_income owner bundle is not canonical",
                ) from error
            if actual_record != expected_record or not (
                actual_record.research_only
                and actual_record.must_not_use_for_decision
                and actual_record.must_not_execute
            ):
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_lifecycle.evidence_substituted",
                    "fixed_income owner record differs from the trial",
                )
            expected_outcome = observation.portfolio_outcome
            actual_outcome = self._portfolio_outcome_provider.get_exact(
                outcome_ref=R5RelativeValuePromotionRef(
                    expected_outcome.outcome_id,
                    expected_outcome.outcome_version,
                ),
                expected_owner_record_hash=expected_outcome.owner_record_hash,
                as_of=as_of,
            )
            if actual_outcome is None:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_lifecycle.portfolio_outcome_missing",
                    "exact Portfolio outcome is unavailable",
                )
            if actual_outcome != expected_outcome or not (
                actual_outcome.is_active_at(as_of)
                and actual_outcome.research_only
                and actual_outcome.must_not_use_for_decision
                and actual_outcome.must_not_execute
            ):
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_lifecycle.evidence_substituted",
                    "Portfolio outcome differs from the trial",
                )


class ApplyR5RelativeValuePromotionLifecycle:
    """Append one owner-authorized transition after full dynamic replay."""

    def __init__(
        self,
        *,
        policy_provider: ExactR5RelativeValuePromotionPolicyProvider,
        trial_provider: ExactR5RelativeValuePromotionTrialProvider,
        owner_record_provider: ExactR5RelativeValueOwnerRecordProvider,
        portfolio_outcome_provider: ExactR5PortfolioOutcomeProvider,
        decision_authorization_provider: ExactR5RelativeValueDecisionAuthorizationProvider,
        lifecycle_authorization_provider: ExactR5RelativeValueLifecycleAuthorizationProvider,
        repository: R5RelativeValuePromotionLifecycleRepository,
    ) -> None:
        self._authorization_provider = lifecycle_authorization_provider
        self._repository = repository
        self._reader = _R5DecisionOwnerGraphReader(
            policy_provider=policy_provider,
            trial_provider=trial_provider,
            owner_record_provider=owner_record_provider,
            portfolio_outcome_provider=portfolio_outcome_provider,
            decision_authorization_provider=decision_authorization_provider,
            repository=repository,
        )
        if lifecycle_authorization_provider.unit_of_work_key != repository.unit_of_work_key:
            raise ValueError("R5 lifecycle authorization uses a different unit of work")

    def execute(
        self,
        command: ApplyR5RelativeValueLifecycleCommand,
    ) -> R5RelativeValueLifecycleEvent:
        """Resolve IDs, replay the full stream and append the exact event."""

        with self._repository.atomic():
            evidence = self._load_authorization(command)
            require_current = command.action is not R5RelativeValueLifecycleAction.RETIRE
            decision_bundle = self._reader.load(
                command.decision_ref,
                knowledge_as_of=evidence.occurred_at,
                require_current=require_current,
            )
            target_bundle = (
                None
                if command.rollback_target_ref is None
                else self._reader.load(
                    command.rollback_target_ref,
                    knowledge_as_of=evidence.occurred_at,
                    require_current=True,
                )
            )
            self._match_authorization(
                command,
                evidence,
                decision_bundle.decision,
                None if target_bundle is None else target_bundle.decision,
            )
            history = self._repository.load_lifecycle_stream(command.scope_ref)
            self._verify_stream(history, command.scope_ref)
            existing = self._repository.get_event_bundle_by_authorization(command.authorization_ref)
            if existing is not None:
                self._verify_existing_winner(
                    existing,
                    evidence,
                    decision_bundle.decision,
                    None if target_bundle is None else target_bundle.decision,
                    history,
                )
                return existing.event
            events = tuple(item.event for item in history)
            if events and events[-1].recorded_at > evidence.occurred_at:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_lifecycle.stale_authorization",
                    "authorization predates the current stream head",
                )
            try:
                event = self._build_event(
                    command=command,
                    evidence=evidence,
                    decision=decision_bundle.decision,
                    rollback_target=(None if target_bundle is None else target_bundle.decision),
                    previous_events=events,
                )
                bundle = R5RelativeValueLifecycleEventBundle.create(
                    event=event,
                    authorization_evidence=evidence,
                )
            except ValueError as error:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_lifecycle.transition_invalid",
                    "authorization or stream does not permit the transition",
                ) from error
            persisted = self._repository.append_lifecycle_event_bundle(bundle)
            if persisted != bundle:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_lifecycle.repository_conflict",
                    "repository changed the exact lifecycle event bundle",
                )
            final_history = self._repository.load_lifecycle_stream(command.scope_ref)
            self._verify_stream(final_history, command.scope_ref)
            if len(final_history) != len(history) + 1 or final_history[-1] != bundle:
                raise R5RelativeValuePromotionEvidenceError(
                    "r5_lifecycle.repository_conflict",
                    "appended event is absent from the canonical full stream",
                )
            return persisted.event

    def _load_authorization(
        self,
        command: ApplyR5RelativeValueLifecycleCommand,
    ) -> R5RelativeValueLifecycleAuthorizationEvidence:
        evidence = self._authorization_provider.get_exact(
            authorization_ref=command.authorization_ref,
            scope_ref=command.scope_ref,
            action=command.action,
            decision_ref=command.decision_ref,
            rollback_target_ref=command.rollback_target_ref,
        )
        if evidence is None:
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.authorization_missing",
                "exact lifecycle authorization is unavailable",
            )
        if (
            (evidence.evidence_id, evidence.evidence_version)
            != (
                command.authorization_ref.stable_id,
                command.authorization_ref.version,
            )
            or evidence.authorization.scope.scope_id != command.scope_ref.scope_id
            or evidence.authorization.event_type is not _event_type(command.action)
        ):
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.evidence_substituted",
                "lifecycle authorization identity, scope or action differs",
            )
        return evidence

    @staticmethod
    def _match_authorization(
        command: ApplyR5RelativeValueLifecycleCommand,
        evidence: R5RelativeValueLifecycleAuthorizationEvidence,
        decision: R5RelativeValuePromotionDecision,
        rollback_target: R5RelativeValuePromotionDecision | None,
    ) -> None:
        authorization = evidence.authorization
        target_identity = (
            None
            if rollback_target is None
            else R5RelativeValueDecisionIdentity.from_decision(rollback_target)
        )
        if (
            authorization.decision != R5RelativeValueDecisionIdentity.from_decision(decision)
            or authorization.rollback_target != target_identity
            or decision.scope.scope_id != command.scope_ref.scope_id
        ):
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.evidence_substituted",
                "lifecycle authorization decision or rollback target differs",
            )

    @staticmethod
    def _build_event(
        *,
        command: ApplyR5RelativeValueLifecycleCommand,
        evidence: R5RelativeValueLifecycleAuthorizationEvidence,
        decision: R5RelativeValuePromotionDecision,
        rollback_target: R5RelativeValuePromotionDecision | None,
        previous_events: tuple[R5RelativeValueLifecycleEvent, ...],
    ) -> R5RelativeValueLifecycleEvent:
        event_type = _event_type(command.action)
        if not previous_events:
            if event_type is not R5RelativeValueLifecycleEventType.PROMOTED:
                raise ValueError("R5 lifecycle root must be a promotion")
            event = create_r5_relative_value_lifecycle_root(
                event_version=evidence.event_ref.version,
                decision=decision,
                authorization=evidence.authorization,
                reason_codes=evidence.reason_codes,
                occurred_at=evidence.occurred_at,
                recorded_at=evidence.event_recorded_at,
            )
        else:
            event = create_r5_relative_value_lifecycle_event(
                event_version=evidence.event_ref.version,
                previous_events=previous_events,
                event_type=event_type,
                decision=decision,
                rollback_target=rollback_target,
                authorization=evidence.authorization,
                reason_codes=evidence.reason_codes,
                occurred_at=evidence.occurred_at,
                recorded_at=evidence.event_recorded_at,
            )
        if (
            evidence.event_ref != R5RelativeValuePromotionRef(event.event_id, event.event_version)
            or evidence.event_content_hash != event.content_hash
        ):
            raise ValueError("R5 lifecycle evidence output event differs")
        return event

    @staticmethod
    def _verify_stream(
        history: tuple[R5RelativeValueLifecycleEventBundle, ...],
        scope_ref: R5RelativeValueLifecycleScopeRef,
    ) -> None:
        if not history:
            return
        events = tuple(item.event for item in history)
        if any(
            R5RelativeValueLifecycleEventBundle.create(
                event=item.event,
                authorization_evidence=item.authorization_evidence,
            )
            != item
            for item in history
        ):
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.stream_invalid",
                "lifecycle bundle is not canonical",
            )
        if any(event.scope.scope_id != scope_ref.scope_id for event in events):
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.stream_invalid",
                "lifecycle stream crosses scopes",
            )
        try:
            derive_r5_relative_value_lifecycle_state(
                events,
                evaluated_at=max(event.recorded_at for event in events),
            )
        except ValueError as error:
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.stream_invalid",
                "lifecycle stream is forked or missing a prefix",
            ) from error

    @staticmethod
    def _verify_existing_winner(
        existing: R5RelativeValueLifecycleEventBundle,
        evidence: R5RelativeValueLifecycleAuthorizationEvidence,
        decision: R5RelativeValuePromotionDecision,
        rollback_target: R5RelativeValuePromotionDecision | None,
        history: tuple[R5RelativeValueLifecycleEventBundle, ...],
    ) -> None:
        event = existing.event
        if (
            existing.authorization_evidence != evidence
            or existing
            != R5RelativeValueLifecycleEventBundle.create(
                event=event,
                authorization_evidence=evidence,
            )
            or existing not in history
            or event.decision != R5RelativeValueDecisionIdentity.from_decision(decision)
            or event.rollback_target
            != (
                None
                if rollback_target is None
                else R5RelativeValueDecisionIdentity.from_decision(rollback_target)
            )
        ):
            raise R5RelativeValuePromotionEvidenceError(
                "r5_lifecycle.repository_conflict",
                "idempotent winner is absent, substituted or non-canonical",
            )


class GetActiveR5RelativeValuePromotion:
    """PIT provider that returns only a fully revalidated active decision."""

    def __init__(
        self,
        *,
        policy_provider: ExactR5RelativeValuePromotionPolicyProvider,
        trial_provider: ExactR5RelativeValuePromotionTrialProvider,
        owner_record_provider: ExactR5RelativeValueOwnerRecordProvider,
        portfolio_outcome_provider: ExactR5PortfolioOutcomeProvider,
        decision_authorization_provider: ExactR5RelativeValueDecisionAuthorizationProvider,
        repository: R5RelativeValuePromotionLifecycleRepository,
        clock: R5PromotionServerClock,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._reader = _R5DecisionOwnerGraphReader(
            policy_provider=policy_provider,
            trial_provider=trial_provider,
            owner_record_provider=owner_record_provider,
            portfolio_outcome_provider=portfolio_outcome_provider,
            decision_authorization_provider=decision_authorization_provider,
            repository=repository,
        )

    def get_active(
        self,
        scope_ref: R5RelativeValueLifecycleScopeRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionDecisionBundle | None:
        """Replay the PIT prefix and dynamically reread every exact owner."""

        require_aware(as_of, "R5 lifecycle active as_of")
        try:
            require_r5_promotion_pit_cutoff(
                as_of,
                server_now=self._clock.now(),
            )
            with self._repository.atomic():
                history = self._repository.load_lifecycle_stream(scope_ref)
                ApplyR5RelativeValuePromotionLifecycle._verify_stream(
                    history,
                    scope_ref,
                )
                prefix = tuple(item.event for item in history if item.event.recorded_at <= as_of)
                if not prefix:
                    return None
                snapshot = derive_r5_relative_value_lifecycle_state(
                    prefix,
                    evaluated_at=as_of,
                )
                if snapshot.active_decision is None:
                    return None
                identity = snapshot.active_decision
                bundle = self._reader.load(
                    R5RelativeValuePromotionRef(
                        identity.decision_id,
                        identity.decision_version,
                    ),
                    knowledge_as_of=as_of,
                    require_current=True,
                )
                if R5RelativeValueDecisionIdentity.from_decision(
                    bundle.decision
                ) != identity or not (
                    bundle.decision.research_only
                    and bundle.decision.must_not_use_for_decision
                    and bundle.decision.must_not_execute
                ):
                    return None
                return bundle
        except (R5RelativeValuePromotionEvidenceError, ValueError):
            return None


__all__ = [
    "ApplyR5RelativeValueLifecycleCommand",
    "ApplyR5RelativeValuePromotionLifecycle",
    "ExactR5RelativeValueLifecycleAuthorizationProvider",
    "GetActiveR5RelativeValuePromotion",
    "R5RelativeValueLifecycleAction",
    "R5RelativeValueLifecycleAuthorizationEvidence",
    "R5RelativeValueLifecycleEventBundle",
    "R5RelativeValueLifecycleScopeRef",
    "R5RelativeValuePromotionLifecycleRepository",
    "r5_relative_value_lifecycle_evidence_hash",
]
