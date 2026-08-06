"""Exact R4 promotion trial seal over Portfolio and current R3 evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind

from .r4_promotion_evidence import R4PromotionR3AttestationEvidence
from .r4_promotion_record_seal import R4PromotionPortfolioRecordSeal
from .r4_promotion_scope_policy import (
    R4PromotionPolicy,
    R4PromotionScope,
    _decimal_text,
    _hash_payload,
    _require_aware,
    _require_hash,
    _require_token,
    _utc_text,
)


class R4PromotionTrialState(str, Enum):
    """Evidence readiness derived without caller-provided eligibility."""

    READY_FOR_POLICY_EVALUATION = "ready_for_policy_evaluation"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class R4PromotionTrialSeal:
    """Complete exact trial identity used by a Research decision."""

    trial_id: str
    trial_version: str
    owner: str
    capability: str
    purpose: str
    scope: R4PromotionScope
    policy_id: str
    policy_version: str
    policy_content_hash: str
    portfolio_record: R4PromotionPortfolioRecordSeal
    current_r3_attestation: R4PromotionR3AttestationEvidence
    observed_fold_count: int
    regime_coverage_ratio: Decimal
    available_methods: tuple[MacroRiskCandidateKind, ...]
    state: R4PromotionTrialState
    blocker_codes: tuple[str, ...]
    evaluated_at: datetime
    valid_until: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        trial_id: str,
        trial_version: str,
        policy: R4PromotionPolicy,
        portfolio_record: R4PromotionPortfolioRecordSeal,
        current_r3_attestation: R4PromotionR3AttestationEvidence,
        evaluated_at: datetime,
    ) -> R4PromotionTrialSeal:
        """Validate preregistration and derive trial readiness and validity."""

        _validate_registration(policy, portfolio_record)
        if portfolio_record.record_r3_attestation != current_r3_attestation:
            raise ValueError("current authoritative R3 attestation differs from the record")
        if not current_r3_attestation.is_active_at(evaluated_at):
            raise ValueError("current authoritative R3 attestation is inactive")
        if not portfolio_record.recorded_at <= evaluated_at < portfolio_record.valid_until:
            raise ValueError("Portfolio owner record is unavailable at trial evaluation")
        observed_fold_count = len(portfolio_record.windows)
        regime_coverage_ratio = Decimal(len(portfolio_record.regime_covered_fold_ids)) / Decimal(
            observed_fold_count
        )
        available_methods = tuple(item.method for item in portfolio_record.method_summaries)
        blocker_codes = _trial_blockers(
            policy=policy,
            record=portfolio_record,
            observed_fold_count=observed_fold_count,
            regime_coverage_ratio=regime_coverage_ratio,
            available_methods=available_methods,
        )
        state = (
            R4PromotionTrialState.READY_FOR_POLICY_EVALUATION
            if not blocker_codes
            else R4PromotionTrialState.BLOCKED
        )
        valid_until = min(
            portfolio_record.valid_until,
            current_r3_attestation.effective_valid_until,
        )
        values = (
            trial_id,
            trial_version,
            "research",
            "r4",
            "macro_risk_method_research",
            policy.scope,
            policy.policy_id,
            policy.policy_version,
            policy.content_hash,
            portfolio_record,
            current_r3_attestation,
            observed_fold_count,
            regime_coverage_ratio,
            available_methods,
            state,
            blocker_codes,
            evaluated_at,
            valid_until,
        )
        digest = _hash_payload(_trial_payload(*values))
        return cls(*values, digest)

    def __post_init__(self) -> None:
        _require_token(self.trial_id, "R4 promotion trial_id")
        _require_token(self.trial_version, "R4 promotion trial_version")
        if (
            self.owner != "research"
            or self.capability != "r4"
            or self.purpose != "macro_risk_method_research"
        ):
            raise ValueError("R4 promotion trial authority is invalid")
        if (
            self.scope.owner != self.owner
            or self.scope.capability != self.capability
            or self.scope.purpose != self.purpose
        ):
            raise ValueError("R4 promotion trial crosses authority scopes")
        _require_token(self.policy_id, "R4 promotion trial policy_id")
        _require_token(self.policy_version, "R4 promotion trial policy_version")
        _require_hash(self.policy_content_hash, "R4 promotion trial policy_content_hash")
        if isinstance(self.observed_fold_count, bool) or self.observed_fold_count < 1:
            raise ValueError("R4 promotion observed_fold_count must be positive")
        if not Decimal("0") <= self.regime_coverage_ratio <= Decimal("1"):
            raise ValueError("R4 promotion regime coverage must be within [0, 1]")
        if self.available_methods != tuple(
            sorted(set(self.available_methods), key=lambda item: item.value)
        ):
            raise ValueError("R4 promotion available methods must be unique and ordered")
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("R4 promotion trial blockers must be unique and ordered")
        if (self.state is R4PromotionTrialState.BLOCKED) != bool(self.blocker_codes):
            raise ValueError("R4 promotion trial state must be derived from blockers")
        _require_aware(self.evaluated_at, "R4 promotion trial evaluated_at")
        _require_aware(self.valid_until, "R4 promotion trial valid_until")
        if not (
            self.portfolio_record.recorded_at
            <= self.evaluated_at
            < self.valid_until
            <= self.portfolio_record.valid_until
            and self.valid_until <= self.current_r3_attestation.effective_valid_until
        ):
            raise ValueError("R4 promotion trial knowledge/validity window is invalid")
        if self.portfolio_record.record_r3_attestation != self.current_r3_attestation:
            raise ValueError("R4 promotion trial current R3 evidence was substituted")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R4 promotion trial must remain research-only")
        _require_hash(self.content_hash, "R4 promotion trial content_hash")
        if self.content_hash != r4_promotion_trial_seal_hash(self):
            raise ValueError("R4 promotion trial content hash mismatch")


def _validate_registration(
    policy: R4PromotionPolicy,
    record: R4PromotionPortfolioRecordSeal,
) -> None:
    registration = policy.registration
    if record.study_id != registration.study_id:
        raise ValueError("Portfolio study identity is outside the preregistered family")
    if record.split_policy_version != registration.split_policy_version:
        raise ValueError("Portfolio split policy differs from preregistration")
    if record.cost_semantics_version != registration.cost_semantics_version:
        raise ValueError("Portfolio cost semantics differ from preregistration")
    if any(
        window.asset_codes != registration.asset_codes
        or window.factor_codes != registration.factor_codes
        for window in record.windows
    ):
        raise ValueError("Portfolio universe or factor family differs from preregistration")
    minimum_selection = min(item.selection_as_of for item in record.windows)
    if not (
        policy.recorded_at <= minimum_selection
        and policy.active_from <= minimum_selection < policy.active_until
    ):
        raise ValueError("R4 promotion policy was not preregistered before selection")


def _trial_blockers(
    *,
    policy: R4PromotionPolicy,
    record: R4PromotionPortfolioRecordSeal,
    observed_fold_count: int,
    regime_coverage_ratio: Decimal,
    available_methods: tuple[MacroRiskCandidateKind, ...],
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not record.artifact_evidence_complete:
        blockers.append("portfolio_artifact_incomplete")
    if not record.artifact_eligible or record.artifact_blockers:
        blockers.append("portfolio_artifact_ineligible")
    if observed_fold_count < policy.minimum_fold_count:
        blockers.append("minimum_fold_count_not_met")
    if regime_coverage_ratio < policy.minimum_regime_coverage_ratio:
        blockers.append("minimum_regime_coverage_not_met")
    if available_methods != policy.required_methods:
        blockers.append("required_method_family_incomplete")
    expected_metric_keys = {
        (window.fold_id, method) for window in record.windows for method in policy.required_methods
    }
    if {(item.fold_id, item.method) for item in record.window_metrics} != expected_metric_keys:
        blockers.append("window_metric_family_incomplete")
    if any(item.window_count != observed_fold_count for item in record.method_summaries):
        blockers.append("method_summary_fold_count_mismatch")
    return tuple(sorted(set(blockers)))


def _trial_payload(
    trial_id: str,
    trial_version: str,
    owner: str,
    capability: str,
    purpose: str,
    scope: R4PromotionScope,
    policy_id: str,
    policy_version: str,
    policy_content_hash: str,
    portfolio_record: R4PromotionPortfolioRecordSeal,
    current_r3_attestation: R4PromotionR3AttestationEvidence,
    observed_fold_count: int,
    regime_coverage_ratio: Decimal,
    available_methods: tuple[MacroRiskCandidateKind, ...],
    state: R4PromotionTrialState,
    blocker_codes: tuple[str, ...],
    evaluated_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r4-promotion-trial-seal.v1",
        "identity": [trial_id, trial_version, owner, capability, purpose],
        "scope": [scope.scope_id, scope.content_hash],
        "policy": [policy_id, policy_version, policy_content_hash],
        "portfolio_record": [
            portfolio_record.record_id,
            portfolio_record.record_hash,
            portfolio_record.content_hash,
            portfolio_record.owner_record_key,
        ],
        "all_record_subhashes": [list(item) for item in portfolio_record.record_subhashes],
        "current_r3_attestation": [
            current_r3_attestation.attestation_hash,
            current_r3_attestation.content_hash,
        ],
        "study": [
            portfolio_record.study_id,
            portfolio_record.study_version,
            portfolio_record.study_content_hash,
            portfolio_record.split_contract_hash,
            portfolio_record.split_policy_version,
        ],
        "universe_windows": [item.content_hash for item in portfolio_record.windows],
        "window_metrics": [item.content_hash for item in portfolio_record.window_metrics],
        "method_summaries": [item.content_hash for item in portfolio_record.method_summaries],
        "reproducibility": [
            portfolio_record.producer_code_version,
            portfolio_record.dependency_lock_hash,
        ],
        "observed": [
            observed_fold_count,
            _decimal_text(regime_coverage_ratio),
            [item.value for item in available_methods],
        ],
        "state": [state.value, list(blocker_codes)],
        "window": [_utc_text(evaluated_at), _utc_text(valid_until)],
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r4_promotion_trial_seal_hash(trial: R4PromotionTrialSeal) -> str:
    """Recompute the complete exact R4 promotion trial hash."""

    return _hash_payload(
        _trial_payload(
            trial.trial_id,
            trial.trial_version,
            trial.owner,
            trial.capability,
            trial.purpose,
            trial.scope,
            trial.policy_id,
            trial.policy_version,
            trial.policy_content_hash,
            trial.portfolio_record,
            trial.current_r3_attestation,
            trial.observed_fold_count,
            trial.regime_coverage_ratio,
            trial.available_methods,
            trial.state,
            trial.blocker_codes,
            trial.evaluated_at,
            trial.valid_until,
        )
    )


__all__ = [
    "R4PromotionTrialSeal",
    "R4PromotionTrialState",
    "r4_promotion_trial_seal_hash",
]
