"""ID-only application orchestration for exact R4 promotion decisions."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.application.macro_risk_rolling_research import (
    ExactR3PromotionProvider,
)
from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchExactQuery,
)
from apps.research.application.r4_promotion_projection import (
    project_r4_portfolio_owner_record,
    project_r4_promotion_r3_attestation,
)
from apps.research.domain.r4_promotion_decision import (
    R4PromotionDecision,
    create_r4_promotion_decision,
    r4_promotion_decision_valid_until,
)
from apps.research.domain.r4_promotion_scope_policy import (
    R4PromotionPolicy,
    _hash_payload,
    _require_aware,
    _require_hash,
    _require_token,
    _utc_text,
)
from apps.research.domain.r4_promotion_trial import R4PromotionTrialSeal


@dataclass(frozen=True)
class R4PromotionVersionRef:
    """ID-only immutable artifact reference."""

    stable_id: str
    version: str

    def __post_init__(self) -> None:
        _require_token(self.stable_id, "R4 promotion stable_id")
        _require_token(self.version, "R4 promotion version")


@dataclass(frozen=True)
class R4PromotionDecisionReceipt:
    """Research-owner/server receipt for one exact decision identity."""

    receipt_id: str
    receipt_version: str
    owner: str
    capability: str
    purpose: str
    decision_ref: R4PromotionVersionRef
    trial_ref: R4PromotionVersionRef
    policy_ref: R4PromotionVersionRef
    policy_content_hash: str
    portfolio_record_id: str
    portfolio_record_hash: str
    portfolio_owner_record_key: str
    portfolio_recorded_at: datetime
    current_r3_content_hash: str
    decided_at: datetime
    recorded_at: datetime
    decision_valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        receipt_id: str,
        receipt_version: str,
        decision_ref: R4PromotionVersionRef,
        trial_ref: R4PromotionVersionRef,
        policy_ref: R4PromotionVersionRef,
        policy_content_hash: str,
        portfolio_record_id: str,
        portfolio_record_hash: str,
        portfolio_owner_record_key: str,
        portfolio_recorded_at: datetime,
        current_r3_content_hash: str,
        decided_at: datetime,
        recorded_at: datetime,
        decision_valid_until: datetime,
    ) -> R4PromotionDecisionReceipt:
        """Seal a stable Research receipt claimed by an owner/server provider."""

        values = (
            receipt_id,
            receipt_version,
            "research",
            "r4",
            "macro_risk_method_research",
            decision_ref,
            trial_ref,
            policy_ref,
            policy_content_hash,
            portfolio_record_id,
            portfolio_record_hash,
            portfolio_owner_record_key,
            portfolio_recorded_at,
            current_r3_content_hash,
            decided_at,
            recorded_at,
            decision_valid_until,
        )
        digest = _hash_payload(_decision_receipt_payload(*values))
        return cls(*values, digest)

    def __post_init__(self) -> None:
        _require_token(self.receipt_id, "R4 decision receipt_id")
        _require_token(self.receipt_version, "R4 decision receipt_version")
        if (
            self.owner != "research"
            or self.capability != "r4"
            or self.purpose != "macro_risk_method_research"
        ):
            raise ValueError("R4 decision receipt authority is invalid")
        for identifier_name, identifier_value in (
            ("portfolio_record_id", self.portfolio_record_id),
            ("portfolio_owner_record_key", self.portfolio_owner_record_key),
        ):
            _require_token(identifier_value, f"R4 decision receipt {identifier_name}")
        for hash_name, hash_value in (
            ("policy_content_hash", self.policy_content_hash),
            ("portfolio_record_hash", self.portfolio_record_hash),
            ("current_r3_content_hash", self.current_r3_content_hash),
            ("content_hash", self.content_hash),
        ):
            _require_hash(hash_value, f"R4 decision receipt {hash_name}")
        for clock_name, clock_value in (
            ("portfolio_recorded_at", self.portfolio_recorded_at),
            ("decided_at", self.decided_at),
            ("recorded_at", self.recorded_at),
            ("decision_valid_until", self.decision_valid_until),
        ):
            _require_aware(clock_value, f"R4 decision receipt {clock_name}")
        if not (
            self.portfolio_recorded_at
            <= self.decided_at
            <= self.recorded_at
            < self.decision_valid_until
        ):
            raise ValueError("R4 decision receipt knowledge-time chain is invalid")
        if self.content_hash != r4_promotion_decision_receipt_hash(self):
            raise ValueError("R4 promotion decision receipt hash mismatch")


def _decision_receipt_payload(
    receipt_id: str,
    receipt_version: str,
    owner: str,
    capability: str,
    purpose: str,
    decision_ref: R4PromotionVersionRef,
    trial_ref: R4PromotionVersionRef,
    policy_ref: R4PromotionVersionRef,
    policy_content_hash: str,
    portfolio_record_id: str,
    portfolio_record_hash: str,
    portfolio_owner_record_key: str,
    portfolio_recorded_at: datetime,
    current_r3_content_hash: str,
    decided_at: datetime,
    recorded_at: datetime,
    decision_valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r4-promotion-decision-receipt.v1",
        "identity": [receipt_id, receipt_version, owner, capability, purpose],
        "decision": [decision_ref.stable_id, decision_ref.version],
        "trial": [trial_ref.stable_id, trial_ref.version],
        "policy": [policy_ref.stable_id, policy_ref.version, policy_content_hash],
        "portfolio_record": [
            portfolio_record_id,
            portfolio_record_hash,
            portfolio_owner_record_key,
            _utc_text(portfolio_recorded_at),
        ],
        "current_r3_content_hash": current_r3_content_hash,
        "window": [
            _utc_text(decided_at),
            _utc_text(recorded_at),
            _utc_text(decision_valid_until),
        ],
    }


def r4_promotion_decision_receipt_hash(receipt: R4PromotionDecisionReceipt) -> str:
    """Recompute one Research owner decision receipt hash."""

    return _hash_payload(
        _decision_receipt_payload(
            receipt.receipt_id,
            receipt.receipt_version,
            receipt.owner,
            receipt.capability,
            receipt.purpose,
            receipt.decision_ref,
            receipt.trial_ref,
            receipt.policy_ref,
            receipt.policy_content_hash,
            receipt.portfolio_record_id,
            receipt.portfolio_record_hash,
            receipt.portfolio_owner_record_key,
            receipt.portfolio_recorded_at,
            receipt.current_r3_content_hash,
            receipt.decided_at,
            receipt.recorded_at,
            receipt.decision_valid_until,
        )
    )


@dataclass(frozen=True)
class R4PromotionDecisionBundle:
    """Atomic decision plus Research receipt over exact owner evidence."""

    decision: R4PromotionDecision
    receipt: R4PromotionDecisionReceipt
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        decision: R4PromotionDecision,
        receipt: R4PromotionDecisionReceipt,
    ) -> R4PromotionDecisionBundle:
        """Seal one exact decision persistence unit."""

        digest = _decision_bundle_hash(decision, receipt)
        return cls(decision=decision, receipt=receipt, content_hash=digest)

    def __post_init__(self) -> None:
        if (
            self.receipt.decision_ref
            != R4PromotionVersionRef(self.decision.decision_id, self.decision.decision_version)
            or self.receipt.trial_ref
            != R4PromotionVersionRef(
                self.decision.trial.trial_id, self.decision.trial.trial_version
            )
            or self.receipt.policy_ref
            != R4PromotionVersionRef(
                self.decision.policy.policy_id,
                self.decision.policy.policy_version,
            )
            or self.receipt.policy_content_hash != self.decision.policy.content_hash
            or self.receipt.portfolio_record_id != self.decision.trial.portfolio_record.record_id
            or self.receipt.portfolio_record_hash
            != self.decision.trial.portfolio_record.record_hash
            or self.receipt.portfolio_owner_record_key
            != self.decision.trial.portfolio_record.owner_record_key
            or self.receipt.portfolio_recorded_at
            != self.decision.trial.portfolio_record.recorded_at
            or self.receipt.current_r3_content_hash
            != self.decision.trial.current_r3_attestation.content_hash
            or self.receipt.decided_at != self.decision.decided_at
            or self.receipt.recorded_at != self.decision.recorded_at
            or self.receipt.decision_valid_until != self.decision.valid_until
        ):
            raise ValueError("R4 promotion decision bundle receipt was substituted")
        _require_hash(self.content_hash, "R4 promotion decision bundle content_hash")
        if self.content_hash != _decision_bundle_hash(self.decision, self.receipt):
            raise ValueError("R4 promotion decision bundle hash mismatch")


def _decision_bundle_hash(
    decision: R4PromotionDecision,
    receipt: R4PromotionDecisionReceipt,
) -> str:
    return _hash_payload(
        {
            "schema": "research-r4-promotion-decision-bundle.v1",
            "decision": [
                decision.decision_id,
                decision.decision_version,
                decision.content_hash,
            ],
            "receipt": [
                receipt.receipt_id,
                receipt.receipt_version,
                receipt.content_hash,
            ],
            "portfolio_owner_record_key": receipt.portfolio_owner_record_key,
        }
    )


class ExactR4PromotionPolicyProvider(Protocol):
    """Read one exact pre-registered Research policy at knowledge time."""

    def get_exact(
        self,
        policy_ref: R4PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R4PromotionPolicy | None:
        """Return only the exact active owner policy."""


class R4DecisionReceiptProvider(Protocol):
    """Atomically claim the stable Research owner/server decision receipt."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the receipt transaction boundary."""

    def get_exact(
        self,
        *,
        decision_ref: R4PromotionVersionRef,
        trial_ref: R4PromotionVersionRef,
        policy_ref: R4PromotionVersionRef,
        policy_content_hash: str,
        portfolio_record_id: str,
        portfolio_record_hash: str,
        portfolio_owner_record_key: str,
        portfolio_recorded_at: datetime,
        current_r3_content_hash: str,
        decided_at: datetime,
        decision_valid_until: datetime,
    ) -> R4PromotionDecisionReceipt | None:
        """Return one stable exact receipt or ``None``."""


class R4PromotionDecisionRepository(Protocol):
    """Append-only Phase-A port for exact decision bundles."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the repository transaction boundary."""

    def atomic(self) -> AbstractContextManager[None]:
        """Wrap receipt claim and decision append atomically."""

    def append_decision_bundle(
        self,
        bundle: R4PromotionDecisionBundle,
    ) -> R4PromotionDecisionBundle:
        """Append or return only an exact idempotent winner."""

    def get_decision_bundle(
        self,
        decision_ref: R4PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R4PromotionDecisionBundle | None:
        """Return one exact recorded decision bundle at knowledge time."""


@dataclass(frozen=True)
class EvaluateR4PromotionCommand:
    """ID-only evaluation command; no policy, record, R3, gates or clocks."""

    output_decision_ref: R4PromotionVersionRef
    output_trial_ref: R4PromotionVersionRef
    policy_ref: R4PromotionVersionRef
    portfolio_record_id: str
    expected_portfolio_record_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.portfolio_record_id, "R4 command portfolio_record_id")
        _require_hash(
            self.expected_portfolio_record_hash,
            "R4 command expected_portfolio_record_hash",
        )
        _require_aware(self.as_of, "R4 promotion command as_of")


class R4PromotionEvidenceError(ValueError):
    """Raised when exact owner evidence is missing, late or substituted."""


class EvaluateR4PromotionUseCase:
    """Re-read exact policy, Portfolio and current R3 before decision append."""

    def __init__(
        self,
        *,
        policy_provider: ExactR4PromotionPolicyProvider,
        portfolio_query: R4RollingResearchExactQuery,
        current_r3_provider: ExactR3PromotionProvider,
        receipt_provider: R4DecisionReceiptProvider,
        repository: R4PromotionDecisionRepository,
    ) -> None:
        self._policy_provider = policy_provider
        self._portfolio_query = portfolio_query
        self._current_r3_provider = current_r3_provider
        self._receipt_provider = receipt_provider
        self._repository = repository
        unit_of_work_keys = {
            portfolio_query.unit_of_work_key,
            receipt_provider.unit_of_work_key,
            repository.unit_of_work_key,
        }
        if len(unit_of_work_keys) != 1:
            raise ValueError(
                "R4 Portfolio query, decision receipt and repository use different units of work"
            )

    def execute(self, command: EvaluateR4PromotionCommand) -> R4PromotionDecision:
        """Resolve exact inputs, derive the outcome and require exact append."""

        with self._repository.atomic():
            return self._evaluate_and_append_atomic(command)

    def _evaluate_and_append_atomic(
        self,
        command: EvaluateR4PromotionCommand,
    ) -> R4PromotionDecision:
        """Re-read every dynamic owner input and append inside one transaction."""

        policy = self._policy_provider.get_exact(command.policy_ref, as_of=command.as_of)
        if policy is None or (
            policy.policy_id,
            policy.policy_version,
        ) != (command.policy_ref.stable_id, command.policy_ref.version):
            raise R4PromotionEvidenceError("exact R4 promotion policy is unavailable")
        owner_record = self._portfolio_query.get_exact(
            record_id=command.portfolio_record_id,
            expected_record_hash=command.expected_portfolio_record_hash,
            as_of=command.as_of,
        )
        if owner_record is None:
            raise R4PromotionEvidenceError("exact Portfolio R4 owner record is unavailable")
        portfolio_record = project_r4_portfolio_owner_record(owner_record)
        source = owner_record.record.promotion_attestation
        current_r3 = self._current_r3_provider.get_exact(
            capability_key="macro_factor_r3",
            artifact_id=source.artifact_id,
            artifact_version=source.artifact_version,
            artifact_content_hash=source.artifact_content_hash,
            decision_id=source.decision_id,
            decision_version=source.decision_version,
            decision_content_hash=source.decision_content_hash,
            as_of=command.as_of,
        )
        if current_r3 is None:
            raise R4PromotionEvidenceError("exact current R3 attestation is unavailable")
        current_r3_evidence = project_r4_promotion_r3_attestation(current_r3)
        try:
            trial = R4PromotionTrialSeal.create(
                trial_id=command.output_trial_ref.stable_id,
                trial_version=command.output_trial_ref.version,
                policy=policy,
                portfolio_record=portfolio_record,
                current_r3_attestation=current_r3_evidence,
                evaluated_at=command.as_of,
            )
        except ValueError as error:
            raise R4PromotionEvidenceError("R4 promotion trial evidence is invalid") from error
        return self._append_atomic(command, policy, trial)

    def _append_atomic(
        self,
        command: EvaluateR4PromotionCommand,
        policy: R4PromotionPolicy,
        trial: R4PromotionTrialSeal,
    ) -> R4PromotionDecision:
        valid_until = r4_promotion_decision_valid_until(
            policy=policy,
            trial=trial,
            as_of=command.as_of,
        )
        receipt = self._receipt_provider.get_exact(
            decision_ref=command.output_decision_ref,
            trial_ref=command.output_trial_ref,
            policy_ref=command.policy_ref,
            policy_content_hash=policy.content_hash,
            portfolio_record_id=trial.portfolio_record.record_id,
            portfolio_record_hash=trial.portfolio_record.record_hash,
            portfolio_owner_record_key=trial.portfolio_record.owner_record_key,
            portfolio_recorded_at=trial.portfolio_record.recorded_at,
            current_r3_content_hash=trial.current_r3_attestation.content_hash,
            decided_at=command.as_of,
            decision_valid_until=valid_until,
        )
        if receipt is None or not _receipt_matches(
            receipt=receipt,
            command=command,
            policy=policy,
            trial=trial,
            valid_until=valid_until,
        ):
            raise R4PromotionEvidenceError("exact Research R4 decision receipt is unavailable")
        decision = create_r4_promotion_decision(
            decision_id=command.output_decision_ref.stable_id,
            decision_version=command.output_decision_ref.version,
            policy=policy,
            trial=trial,
            as_of=command.as_of,
            recorded_at=receipt.recorded_at,
        )
        bundle = R4PromotionDecisionBundle.create(decision=decision, receipt=receipt)
        persisted = self._repository.append_decision_bundle(bundle)
        if persisted != bundle:
            raise R4PromotionEvidenceError("R4 repository changed the exact decision bundle")
        return persisted.decision


def _receipt_matches(
    *,
    receipt: R4PromotionDecisionReceipt,
    command: EvaluateR4PromotionCommand,
    policy: R4PromotionPolicy,
    trial: R4PromotionTrialSeal,
    valid_until: datetime,
) -> bool:
    return (
        receipt.decision_ref == command.output_decision_ref
        and receipt.trial_ref == command.output_trial_ref
        and receipt.policy_ref == command.policy_ref
        and receipt.policy_content_hash == policy.content_hash
        and receipt.portfolio_record_id == trial.portfolio_record.record_id
        and receipt.portfolio_record_hash == trial.portfolio_record.record_hash
        and receipt.portfolio_owner_record_key == trial.portfolio_record.owner_record_key
        and receipt.portfolio_recorded_at == trial.portfolio_record.recorded_at
        and receipt.current_r3_content_hash == trial.current_r3_attestation.content_hash
        and receipt.decided_at == command.as_of
        and receipt.decision_valid_until == valid_until
        and receipt.content_hash == r4_promotion_decision_receipt_hash(receipt)
    )


__all__ = [
    "EvaluateR4PromotionCommand",
    "EvaluateR4PromotionUseCase",
    "ExactR4PromotionPolicyProvider",
    "R4DecisionReceiptProvider",
    "R4PromotionDecisionBundle",
    "R4PromotionDecisionReceipt",
    "R4PromotionDecisionRepository",
    "R4PromotionEvidenceError",
    "R4PromotionVersionRef",
    "r4_promotion_decision_receipt_hash",
]
