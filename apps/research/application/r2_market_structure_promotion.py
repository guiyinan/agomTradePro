"""ID-only orchestration for Research-owned R2 promotion and lifecycle."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.data_center.domain.market_structure import ImmutableMarketStructureEvidence
from apps.fixed_income.domain.evidence import require_aware, require_token
from apps.research.domain.r2_market_structure_promotion import (
    R2MarketStructureDecisionAuthorization,
    R2MarketStructureEvidenceSeal,
    R2MarketStructureLifecycleAction,
    R2MarketStructureLifecycleAuthorization,
    R2MarketStructureLifecycleEvent,
    R2MarketStructurePromotionDecision,
    R2MarketStructurePromotionDecisionOutcome,
    R2MarketStructurePromotionPolicy,
    R2MarketStructurePromotionRef,
    create_r2_market_structure_lifecycle_event,
    create_r2_market_structure_promotion_decision,
    derive_r2_market_structure_active_stack,
)


class R2MarketStructurePromotionEvidenceError(ValueError):
    """Stable fail-closed error for missing or substituted owner evidence."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code


class R2MarketStructurePromotionClock(Protocol):
    """Authoritative server clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


def require_r2_market_structure_pit_cutoff(
    as_of: datetime,
    *,
    server_now: datetime,
) -> None:
    """Reject caller cutoffs later than authoritative server time."""

    require_aware(as_of, "R2 promotion PIT as_of")
    require_aware(server_now, "R2 promotion server_now")
    if as_of > server_now:
        raise R2MarketStructurePromotionEvidenceError(
            "r2_market_structure.future_cutoff",
            "PIT as_of cannot be later than authoritative server time",
        )


class ExactR2MarketStructurePromotionPolicySource(Protocol):
    """Research owner port for an approved policy body."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def get_exact(
        self,
        policy_ref: R2MarketStructurePromotionRef,
        *,
        as_of: datetime,
    ) -> R2MarketStructurePromotionPolicy | None:
        """Return one exact owner-approved policy."""


class ExactR2MarketStructureEvidenceProvider(Protocol):
    """Data Center Application port for exact published R2 evidence."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def get_exact(
        self,
        evidence_ref: R2MarketStructurePromotionRef,
        *,
        as_of: datetime,
    ) -> ImmutableMarketStructureEvidence | None:
        """Return exact immutable evidence known at the PIT."""


class ExactR2MarketStructureDecisionAuthorizationSource(Protocol):
    """Research owner port for one exact decision authorization."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def get_exact(
        self,
        authorization_ref: R2MarketStructurePromotionRef,
        *,
        policy_ref: R2MarketStructurePromotionRef,
        evidence_ref: R2MarketStructurePromotionRef,
        as_of: datetime,
    ) -> R2MarketStructureDecisionAuthorization | None:
        """Return an exact authorization matching every selector."""


class ExactR2MarketStructureLifecycleAuthorizationSource(Protocol):
    """Research owner port for one exact lifecycle authorization."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def get_exact(
        self,
        authorization_ref: R2MarketStructurePromotionRef,
        *,
        scope_id: str,
        action: R2MarketStructureLifecycleAction,
        decision_ref: R2MarketStructurePromotionRef,
        rollback_target_ref: R2MarketStructurePromotionRef | None,
    ) -> R2MarketStructureLifecycleAuthorization | None:
        """Return one exact owner transition receipt."""


class R2MarketStructurePromotionRepository(Protocol):
    """Research persistence port for policy, decision and lifecycle ledgers."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the exact repository transaction boundary."""

    def get_policy(
        self,
        policy_ref: R2MarketStructurePromotionRef,
        *,
        as_of: datetime,
    ) -> R2MarketStructurePromotionPolicy | None:
        """Return one exact persisted policy at PIT."""

    def append_decision(
        self,
        decision: R2MarketStructurePromotionDecision,
    ) -> R2MarketStructurePromotionDecision:
        """Append one exact decision."""

    def get_decision(
        self,
        decision_ref: R2MarketStructurePromotionRef,
        *,
        as_of: datetime,
    ) -> R2MarketStructurePromotionDecision | None:
        """Return one exact persisted decision at PIT."""

    def append_lifecycle_event(
        self,
        event: R2MarketStructureLifecycleEvent,
    ) -> R2MarketStructureLifecycleEvent:
        """Append one exact lifecycle event."""

    def load_lifecycle_stream(
        self,
        scope_id: str,
    ) -> tuple[R2MarketStructureLifecycleEvent, ...]:
        """Return the complete scope-local event chain."""

    def get_event_by_authorization(
        self,
        authorization_ref: R2MarketStructurePromotionRef,
    ) -> R2MarketStructureLifecycleEvent | None:
        """Return an idempotent event winner."""


class R2MarketStructurePolicyRegistrationWriter(Protocol):
    """Closure-bound policy writer accepting only an exact reference."""

    def register(
        self,
        policy_ref: R2MarketStructurePromotionRef,
    ) -> R2MarketStructurePromotionPolicy:
        """Reread and append the exact owner policy."""


class RegisterR2MarketStructurePromotionPolicy:
    """Public ID-only policy registration use case."""

    def __init__(self, writer: R2MarketStructurePolicyRegistrationWriter) -> None:
        self._writer = writer

    def execute(
        self,
        policy_ref: R2MarketStructurePromotionRef,
    ) -> R2MarketStructurePromotionPolicy:
        """Register one exact owner policy without accepting its payload."""

        return self._writer.register(policy_ref)


@dataclass(frozen=True)
class EvaluateR2MarketStructurePromotionCommand:
    """Caller-safe exact decision request."""

    policy_ref: R2MarketStructurePromotionRef
    evidence_ref: R2MarketStructurePromotionRef
    authorization_ref: R2MarketStructurePromotionRef
    as_of: datetime

    def __post_init__(self) -> None:
        require_aware(self.as_of, "R2 promotion command as_of")


class EvaluateR2MarketStructurePromotion:
    """Dynamically reread policy, published evidence and owner authorization."""

    def __init__(
        self,
        *,
        policy_source: ExactR2MarketStructurePromotionPolicySource,
        evidence_provider: ExactR2MarketStructureEvidenceProvider,
        authorization_source: ExactR2MarketStructureDecisionAuthorizationSource,
        repository: R2MarketStructurePromotionRepository,
        clock: R2MarketStructurePromotionClock,
    ) -> None:
        self._policy_source = policy_source
        self._evidence_provider = evidence_provider
        self._authorization_source = authorization_source
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        command: EvaluateR2MarketStructurePromotionCommand,
    ) -> R2MarketStructurePromotionDecision:
        """Create or replay the exact derived research-only decision."""

        require_r2_market_structure_pit_cutoff(
            command.as_of,
            server_now=self._clock.now(),
        )
        with self._repository.atomic():
            policy = self._repository.get_policy(command.policy_ref, as_of=command.as_of)
            owner_policy = self._policy_source.get_exact(
                command.policy_ref,
                as_of=command.as_of,
            )
            if policy is None or owner_policy != policy:
                raise R2MarketStructurePromotionEvidenceError(
                    "r2_market_structure.policy_unavailable",
                    "exact owner-approved policy is unavailable or substituted",
                )
            evidence = self._evidence_provider.get_exact(
                command.evidence_ref,
                as_of=command.as_of,
            )
            if evidence is None:
                raise R2MarketStructurePromotionEvidenceError(
                    "r2_market_structure.evidence_unavailable",
                    "exact published market-structure evidence is unavailable",
                )
            try:
                evidence_seal = R2MarketStructureEvidenceSeal.from_evidence(evidence)
            except ValueError as error:
                raise R2MarketStructurePromotionEvidenceError(
                    "r2_market_structure.evidence_invalid",
                    "market-structure evidence is not promotion eligible",
                ) from error
            if evidence_seal.scope != policy.scope:
                raise R2MarketStructurePromotionEvidenceError(
                    "r2_market_structure.scope_mismatch",
                    "policy and evidence scopes differ",
                )
            authorization = self._authorization_source.get_exact(
                command.authorization_ref,
                policy_ref=command.policy_ref,
                evidence_ref=command.evidence_ref,
                as_of=command.as_of,
            )
            if authorization is None:
                raise R2MarketStructurePromotionEvidenceError(
                    "r2_market_structure.authorization_unavailable",
                    "exact Research owner authorization is unavailable",
                )
            decision = create_r2_market_structure_promotion_decision(
                policy=policy,
                evidence=evidence_seal,
                authorization=authorization,
            )
            if decision.decided_at != command.as_of:
                raise R2MarketStructurePromotionEvidenceError(
                    "r2_market_structure.authorization_clock_mismatch",
                    "authorization did not bind the requested decision clock",
                )
            return self._repository.append_decision(decision)


@dataclass(frozen=True)
class ApplyR2MarketStructureLifecycleCommand:
    """ID-only lifecycle request."""

    scope_id: str
    action: R2MarketStructureLifecycleAction
    decision_ref: R2MarketStructurePromotionRef
    authorization_ref: R2MarketStructurePromotionRef
    rollback_target_ref: R2MarketStructurePromotionRef | None = None

    def __post_init__(self) -> None:
        require_token(self.scope_id, "R2 lifecycle command scope_id", maximum=200)
        if (self.action is R2MarketStructureLifecycleAction.ROLLBACK) != (
            self.rollback_target_ref is not None
        ):
            raise ValueError("R2 lifecycle rollback alone requires one target reference")


class ApplyR2MarketStructurePromotionLifecycle:
    """Append one authorized transition after full stream replay."""

    def __init__(
        self,
        *,
        authorization_source: ExactR2MarketStructureLifecycleAuthorizationSource,
        repository: R2MarketStructurePromotionRepository,
        clock: R2MarketStructurePromotionClock,
    ) -> None:
        self._authorization_source = authorization_source
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        command: ApplyR2MarketStructureLifecycleCommand,
    ) -> R2MarketStructureLifecycleEvent:
        """Apply PROMOTE/RETIRE/ROLLBACK without accepting evidence payloads."""

        with self._repository.atomic():
            winner = self._repository.get_event_by_authorization(command.authorization_ref)
            if winner is not None:
                if (
                    winner.scope_id != command.scope_id
                    or winner.authorization.action is not command.action
                    or winner.decision_ref != command.decision_ref
                    or winner.rollback_target_ref != command.rollback_target_ref
                ):
                    raise R2MarketStructurePromotionEvidenceError(
                        "r2_market_structure.lifecycle_idempotency_conflict",
                        "authorization already belongs to another lifecycle command",
                    )
                return winner
            authorization = self._authorization_source.get_exact(
                command.authorization_ref,
                scope_id=command.scope_id,
                action=command.action,
                decision_ref=command.decision_ref,
                rollback_target_ref=command.rollback_target_ref,
            )
            if authorization is None:
                raise R2MarketStructurePromotionEvidenceError(
                    "r2_market_structure.lifecycle_authorization_unavailable",
                    "exact lifecycle authorization is unavailable",
                )
            require_r2_market_structure_pit_cutoff(
                authorization.occurred_at,
                server_now=self._clock.now(),
            )
            decision = self._repository.get_decision(
                command.decision_ref,
                as_of=authorization.occurred_at,
            )
            if decision is None:
                raise R2MarketStructurePromotionEvidenceError(
                    "r2_market_structure.lifecycle_decision_unavailable",
                    "exact promotion decision is unavailable",
                )
            if (
                command.action is R2MarketStructureLifecycleAction.PROMOTE
                and decision.outcome is not R2MarketStructurePromotionDecisionOutcome.APPROVED
            ):
                raise R2MarketStructurePromotionEvidenceError(
                    "r2_market_structure.lifecycle_decision_rejected",
                    "a rejected decision cannot be promoted",
                )
            target = (
                None
                if command.rollback_target_ref is None
                else self._repository.get_decision(
                    command.rollback_target_ref,
                    as_of=authorization.occurred_at,
                )
            )
            if command.rollback_target_ref is not None and target is None:
                raise R2MarketStructurePromotionEvidenceError(
                    "r2_market_structure.rollback_target_unavailable",
                    "exact rollback target is unavailable",
                )
            history = self._repository.load_lifecycle_stream(command.scope_id)
            try:
                event = create_r2_market_structure_lifecycle_event(
                    history=history,
                    decision=decision,
                    authorization=authorization,
                    rollback_target=target,
                )
            except ValueError as error:
                raise R2MarketStructurePromotionEvidenceError(
                    "r2_market_structure.lifecycle_transition_invalid",
                    "lifecycle stream or transition is invalid",
                ) from error
            return self._repository.append_lifecycle_event(event)


class GetActiveR2MarketStructurePromotion:
    """PIT active provider that dynamically revalidates the complete owner graph."""

    def __init__(
        self,
        *,
        policy_source: ExactR2MarketStructurePromotionPolicySource,
        evidence_provider: ExactR2MarketStructureEvidenceProvider,
        decision_authorization_source: ExactR2MarketStructureDecisionAuthorizationSource,
        lifecycle_authorization_source: ExactR2MarketStructureLifecycleAuthorizationSource,
        repository: R2MarketStructurePromotionRepository,
        clock: R2MarketStructurePromotionClock,
    ) -> None:
        self._policy_source = policy_source
        self._evidence_provider = evidence_provider
        self._decision_authorization_source = decision_authorization_source
        self._lifecycle_authorization_source = lifecycle_authorization_source
        self._repository = repository
        self._clock = clock

    def get_active(
        self,
        scope_id: str,
        *,
        as_of: datetime,
    ) -> R2MarketStructurePromotionDecision | None:
        """Return only a fully revalidated active descriptive research result."""

        try:
            require_r2_market_structure_pit_cutoff(
                as_of,
                server_now=self._clock.now(),
            )
            with self._repository.atomic():
                history = self._repository.load_lifecycle_stream(scope_id)
                prefix = tuple(event for event in history if event.recorded_at <= as_of)
                stack = derive_r2_market_structure_active_stack(prefix)
                if not stack:
                    return None
                decision = self._repository.get_decision(stack[-1], as_of=as_of)
                if decision is None or not decision.is_active_at(as_of):
                    return None
                owner_policy = self._policy_source.get_exact(
                    decision.policy.reference,
                    as_of=as_of,
                )
                if owner_policy != decision.policy:
                    return None
                evidence = self._evidence_provider.get_exact(
                    decision.evidence.reference,
                    as_of=as_of,
                )
                if (
                    evidence is None
                    or R2MarketStructureEvidenceSeal.from_evidence(evidence) != decision.evidence
                ):
                    return None
                decision_authorization = self._decision_authorization_source.get_exact(
                    decision.authorization.reference,
                    policy_ref=decision.policy.reference,
                    evidence_ref=decision.evidence.reference,
                    as_of=as_of,
                )
                if decision_authorization != decision.authorization:
                    return None
                for event in prefix:
                    lifecycle_authorization = self._lifecycle_authorization_source.get_exact(
                        event.authorization.reference,
                        scope_id=event.scope_id,
                        action=event.authorization.action,
                        decision_ref=event.decision_ref,
                        rollback_target_ref=event.rollback_target_ref,
                    )
                    if lifecycle_authorization != event.authorization:
                        return None
                return decision
        except (R2MarketStructurePromotionEvidenceError, ValueError):
            return None


__all__ = [
    "ApplyR2MarketStructureLifecycleCommand",
    "ApplyR2MarketStructurePromotionLifecycle",
    "EvaluateR2MarketStructurePromotion",
    "EvaluateR2MarketStructurePromotionCommand",
    "ExactR2MarketStructureDecisionAuthorizationSource",
    "ExactR2MarketStructureEvidenceProvider",
    "ExactR2MarketStructureLifecycleAuthorizationSource",
    "ExactR2MarketStructurePromotionPolicySource",
    "GetActiveR2MarketStructurePromotion",
    "R2MarketStructurePolicyRegistrationWriter",
    "R2MarketStructurePromotionClock",
    "R2MarketStructurePromotionEvidenceError",
    "R2MarketStructurePromotionRepository",
    "RegisterR2MarketStructurePromotionPolicy",
    "require_r2_market_structure_pit_cutoff",
]
