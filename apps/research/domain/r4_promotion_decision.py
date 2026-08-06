"""Derived Research promotion decision for one exact R4 trial."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind

from .r4_promotion_evidence import R4PromotionMethodSummaryEvidence
from .r4_promotion_scope_policy import (
    R4PromotionPolicy,
    R4PromotionScope,
    _decimal_text,
    _hash_payload,
    _require_aware,
    _require_finite,
    _require_hash,
    _require_token,
    _utc_text,
)
from .r4_promotion_trial import R4PromotionTrialSeal, R4PromotionTrialState


class R4PromotionDecisionOutcome(str, Enum):
    """Automatically derived R4 promotion outcome."""

    APPROVED = "approved"
    REJECTED = "rejected"


class R4PromotionGateCode(str, Enum):
    """Stable policy gates over one exact R4 trial."""

    TRIAL_READY = "trial_ready"
    REQUIRED_METHODS = "required_methods"
    MINIMUM_FOLDS = "minimum_folds"
    REGIME_COVERAGE = "regime_coverage"
    RELATIVE_NET_RETURN = "relative_net_return"
    RELATIVE_DRAWDOWN = "relative_drawdown"
    RELATIVE_VOLATILITY = "relative_volatility"
    RELATIVE_COST = "relative_cost"


@dataclass(frozen=True)
class R4RelativeMethodEvidence:
    """Server-derived target-versus-reference net and risk deltas."""

    target_method: MacroRiskCandidateKind
    reference_method: MacroRiskCandidateKind
    target_net_return: Decimal
    reference_net_return: Decimal
    relative_net_return: Decimal
    target_drawdown: Decimal
    reference_drawdown: Decimal
    relative_drawdown_increase: Decimal
    target_volatility: Decimal
    reference_volatility: Decimal
    relative_volatility_increase: Decimal
    target_cost: Decimal
    reference_cost: Decimal
    relative_cost_increase: Decimal
    target_summary_hash: str
    reference_summary_hash: str
    content_hash: str

    @classmethod
    def from_summaries(
        cls,
        *,
        target: R4PromotionMethodSummaryEvidence,
        reference: R4PromotionMethodSummaryEvidence,
    ) -> R4RelativeMethodEvidence:
        """Derive every policy metric from exact Portfolio summaries."""

        target_net = target.compounded_gross_return - target.total_expected_cost
        reference_net = reference.compounded_gross_return - reference.total_expected_cost
        target_volatility = target.realized_variance.sqrt()
        reference_volatility = reference.realized_variance.sqrt()
        values = (
            target.method,
            reference.method,
            target_net,
            reference_net,
            target_net - reference_net,
            target.maximum_drawdown,
            reference.maximum_drawdown,
            target.maximum_drawdown - reference.maximum_drawdown,
            target_volatility,
            reference_volatility,
            target_volatility - reference_volatility,
            target.total_expected_cost,
            reference.total_expected_cost,
            target.total_expected_cost - reference.total_expected_cost,
            target.source_content_hash,
            reference.source_content_hash,
        )
        digest = _hash_payload(_relative_payload(*values))
        return cls(*values, digest)

    def __post_init__(self) -> None:
        if self.target_method is not MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY:
            raise ValueError("R4 relative target must be macro-factor risk parity")
        if self.reference_method is self.target_method:
            raise ValueError("R4 relative reference cannot equal the target")
        for metric_name, metric_value in (
            ("target_net_return", self.target_net_return),
            ("reference_net_return", self.reference_net_return),
            ("relative_net_return", self.relative_net_return),
            ("target_drawdown", self.target_drawdown),
            ("reference_drawdown", self.reference_drawdown),
            ("relative_drawdown_increase", self.relative_drawdown_increase),
            ("target_volatility", self.target_volatility),
            ("reference_volatility", self.reference_volatility),
            ("relative_volatility_increase", self.relative_volatility_increase),
            ("target_cost", self.target_cost),
            ("reference_cost", self.reference_cost),
            ("relative_cost_increase", self.relative_cost_increase),
        ):
            _require_finite(metric_value, f"R4 relative {metric_name}")
        if self.target_volatility < 0 or self.reference_volatility < 0:
            raise ValueError("R4 relative volatility cannot be negative")
        for hash_name, hash_value in (
            ("target_summary_hash", self.target_summary_hash),
            ("reference_summary_hash", self.reference_summary_hash),
            ("content_hash", self.content_hash),
        ):
            _require_hash(hash_value, f"R4 relative {hash_name}")
        if self.content_hash != r4_relative_method_evidence_hash(self):
            raise ValueError("R4 relative method evidence hash mismatch")


def _relative_payload(
    target_method: MacroRiskCandidateKind,
    reference_method: MacroRiskCandidateKind,
    target_net_return: Decimal,
    reference_net_return: Decimal,
    relative_net_return: Decimal,
    target_drawdown: Decimal,
    reference_drawdown: Decimal,
    relative_drawdown_increase: Decimal,
    target_volatility: Decimal,
    reference_volatility: Decimal,
    relative_volatility_increase: Decimal,
    target_cost: Decimal,
    reference_cost: Decimal,
    relative_cost_increase: Decimal,
    target_summary_hash: str,
    reference_summary_hash: str,
) -> dict[str, object]:
    return {
        "schema": "research-r4-relative-method-evidence.v1",
        "methods": [target_method.value, reference_method.value],
        "net_return": [
            _decimal_text(target_net_return),
            _decimal_text(reference_net_return),
            _decimal_text(relative_net_return),
        ],
        "drawdown": [
            _decimal_text(target_drawdown),
            _decimal_text(reference_drawdown),
            _decimal_text(relative_drawdown_increase),
        ],
        "volatility": [
            _decimal_text(target_volatility),
            _decimal_text(reference_volatility),
            _decimal_text(relative_volatility_increase),
        ],
        "cost": [
            _decimal_text(target_cost),
            _decimal_text(reference_cost),
            _decimal_text(relative_cost_increase),
        ],
        "summary_hashes": [target_summary_hash, reference_summary_hash],
    }


def r4_relative_method_evidence_hash(evidence: R4RelativeMethodEvidence) -> str:
    """Recompute one exact relative-method evidence hash."""

    return _hash_payload(
        _relative_payload(
            evidence.target_method,
            evidence.reference_method,
            evidence.target_net_return,
            evidence.reference_net_return,
            evidence.relative_net_return,
            evidence.target_drawdown,
            evidence.reference_drawdown,
            evidence.relative_drawdown_increase,
            evidence.target_volatility,
            evidence.reference_volatility,
            evidence.relative_volatility_increase,
            evidence.target_cost,
            evidence.reference_cost,
            evidence.relative_cost_increase,
            evidence.target_summary_hash,
            evidence.reference_summary_hash,
        )
    )


@dataclass(frozen=True)
class R4PromotionGateOutcome:
    """One deterministic gate observation, including auditable failure values."""

    gate_code: R4PromotionGateCode
    reference_method: MacroRiskCandidateKind | None
    passes: bool
    reason_code: str
    observed_value: Decimal | None
    required_value: Decimal

    def __post_init__(self) -> None:
        relative_gate = self.gate_code in {
            R4PromotionGateCode.RELATIVE_NET_RETURN,
            R4PromotionGateCode.RELATIVE_DRAWDOWN,
            R4PromotionGateCode.RELATIVE_VOLATILITY,
            R4PromotionGateCode.RELATIVE_COST,
        }
        if relative_gate != (self.reference_method is not None):
            raise ValueError("R4 relative gate requires exactly one reference method")
        if type(self.passes) is not bool:
            raise ValueError("R4 promotion gate passes must be boolean")
        suffix = "" if self.reference_method is None else f":{self.reference_method.value}"
        expected_reason = "" if self.passes else f"{self.gate_code.value}{suffix}_not_met"
        if self.reason_code != expected_reason:
            raise ValueError("R4 promotion gate reason does not match its state")
        _require_finite(self.required_value, "R4 promotion gate required_value")
        if self.observed_value is not None:
            _require_finite(self.observed_value, "R4 promotion gate observed_value")
        if self.passes and self.observed_value is None:
            raise ValueError("passing R4 promotion gate requires an observed value")


@dataclass(frozen=True)
class R4PromotionDecision:
    """Research-owned outcome derived over one exact R4 trial and policy."""

    decision_id: str
    decision_version: str
    owner: str
    capability: str
    purpose: str
    scope: R4PromotionScope
    outcome: R4PromotionDecisionOutcome
    policy: R4PromotionPolicy
    trial: R4PromotionTrialSeal
    relative_method_evidence: tuple[R4RelativeMethodEvidence, ...]
    gate_outcomes: tuple[R4PromotionGateOutcome, ...]
    reason_codes: tuple[str, ...]
    decided_at: datetime
    recorded_at: datetime
    valid_until: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        _require_token(self.decision_id, "R4 promotion decision_id")
        _require_token(self.decision_version, "R4 promotion decision_version")
        if (
            self.owner != "research"
            or self.capability != "r4"
            or self.purpose != "macro_risk_method_research"
        ):
            raise ValueError("R4 promotion decision authority is invalid")
        if (
            self.scope != self.policy.scope
            or self.scope != self.trial.scope
            or self.trial.policy_id != self.policy.policy_id
            or self.trial.policy_version != self.policy.policy_version
            or self.trial.policy_content_hash != self.policy.content_hash
        ):
            raise ValueError("R4 promotion decision policy or scope was substituted")
        expected_relative = _relative_evidence(self.policy, self.trial)
        if self.relative_method_evidence != expected_relative:
            raise ValueError("R4 promotion relative method evidence was substituted")
        expected_gates = _evaluate_gates(self.policy, self.trial, expected_relative)
        if self.gate_outcomes != expected_gates:
            raise ValueError("R4 promotion gate outcomes were substituted")
        failures = tuple(sorted(item.reason_code for item in expected_gates if not item.passes))
        if self.outcome is R4PromotionDecisionOutcome.APPROVED:
            if failures or self.reason_codes != ("r4_promotion_policy_satisfied",):
                raise ValueError("approved R4 promotion requires every policy gate")
        elif not failures or self.reason_codes != failures:
            raise ValueError("rejected R4 promotion reasons must match gate evidence")
        _require_aware(self.decided_at, "R4 promotion decided_at")
        _require_aware(self.recorded_at, "R4 promotion recorded_at")
        _require_aware(self.valid_until, "R4 promotion valid_until")
        if not (
            self.trial.evaluated_at
            <= self.decided_at
            <= self.recorded_at
            < self.valid_until
            <= self.policy.active_until
            and self.valid_until <= self.trial.portfolio_record.valid_until
            and self.valid_until <= self.trial.current_r3_attestation.effective_valid_until
        ):
            raise ValueError("R4 promotion decision validity is outside exact evidence")
        if not self.policy.is_active_at(self.decided_at):
            raise ValueError("R4 promotion policy is inactive at decision time")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R4 promotion decision must remain research-only")
        _require_hash(self.content_hash, "R4 promotion decision content_hash")
        if self.content_hash != r4_promotion_decision_hash(self):
            raise ValueError("R4 promotion decision content hash mismatch")


def create_r4_promotion_decision(
    *,
    decision_id: str,
    decision_version: str,
    policy: R4PromotionPolicy,
    trial: R4PromotionTrialSeal,
    as_of: datetime,
    recorded_at: datetime,
) -> R4PromotionDecision:
    """Derive outcome, reasons and validity without caller-provided gate values."""

    _require_aware(as_of, "R4 promotion as_of")
    _require_aware(recorded_at, "R4 promotion recorded_at")
    if not policy.is_active_at(as_of):
        raise ValueError("R4 promotion policy is unavailable or inactive")
    if not trial.evaluated_at <= as_of < trial.valid_until:
        raise ValueError("R4 promotion trial is unavailable or inactive")
    relative = _relative_evidence(policy, trial)
    gates = _evaluate_gates(policy, trial, relative)
    failures = tuple(sorted(item.reason_code for item in gates if not item.passes))
    outcome = (
        R4PromotionDecisionOutcome.APPROVED if not failures else R4PromotionDecisionOutcome.REJECTED
    )
    reasons = ("r4_promotion_policy_satisfied",) if not failures else failures
    valid_until = r4_promotion_decision_valid_until(
        policy=policy,
        trial=trial,
        as_of=as_of,
    )
    values = (
        decision_id,
        decision_version,
        "research",
        "r4",
        "macro_risk_method_research",
        policy.scope,
        outcome,
        policy,
        trial,
        relative,
        gates,
        reasons,
        as_of,
        recorded_at,
        valid_until,
    )
    digest = _hash_payload(_decision_payload(*values))
    return R4PromotionDecision(*values, digest)


def r4_promotion_decision_valid_until(
    *,
    policy: R4PromotionPolicy,
    trial: R4PromotionTrialSeal,
    as_of: datetime,
) -> datetime:
    """Return min(policy, Portfolio record, current R3, policy duration)."""

    _require_aware(as_of, "R4 promotion validity as_of")
    return min(
        policy.active_until,
        trial.portfolio_record.valid_until,
        trial.current_r3_attestation.effective_valid_until,
        as_of + timedelta(seconds=policy.decision_validity_seconds),
    )


def _relative_evidence(
    policy: R4PromotionPolicy,
    trial: R4PromotionTrialSeal,
) -> tuple[R4RelativeMethodEvidence, ...]:
    summaries = {item.method: item for item in trial.portfolio_record.method_summaries}
    target = summaries.get(policy.scope.target_method)
    if target is None:
        return ()
    return tuple(
        R4RelativeMethodEvidence.from_summaries(
            target=target,
            reference=summaries[reference],
        )
        for reference in policy.reference_methods
        if reference in summaries
    )


def _evaluate_gates(
    policy: R4PromotionPolicy,
    trial: R4PromotionTrialSeal,
    relative: tuple[R4RelativeMethodEvidence, ...],
) -> tuple[R4PromotionGateOutcome, ...]:
    values: list[R4PromotionGateOutcome] = []
    values.extend(
        (
            _gate(
                R4PromotionGateCode.TRIAL_READY,
                passes=trial.state is R4PromotionTrialState.READY_FOR_POLICY_EVALUATION,
                observed=Decimal("1") if not trial.blocker_codes else Decimal("0"),
                required=Decimal("1"),
            ),
            _gate(
                R4PromotionGateCode.REQUIRED_METHODS,
                passes=trial.available_methods == policy.required_methods,
                observed=Decimal(len(trial.available_methods)),
                required=Decimal(len(policy.required_methods)),
            ),
            _gate(
                R4PromotionGateCode.MINIMUM_FOLDS,
                passes=trial.observed_fold_count >= policy.minimum_fold_count,
                observed=Decimal(trial.observed_fold_count),
                required=Decimal(policy.minimum_fold_count),
            ),
            _gate(
                R4PromotionGateCode.REGIME_COVERAGE,
                passes=(trial.regime_coverage_ratio >= policy.minimum_regime_coverage_ratio),
                observed=trial.regime_coverage_ratio,
                required=policy.minimum_regime_coverage_ratio,
            ),
        )
    )
    by_reference = {item.reference_method: item for item in relative}
    for reference in policy.reference_methods:
        evidence = by_reference.get(reference)
        values.extend(
            (
                _relative_gate(
                    R4PromotionGateCode.RELATIVE_NET_RETURN,
                    reference,
                    None if evidence is None else evidence.relative_net_return,
                    policy.minimum_relative_net_return,
                    minimum=True,
                ),
                _relative_gate(
                    R4PromotionGateCode.RELATIVE_DRAWDOWN,
                    reference,
                    None if evidence is None else evidence.relative_drawdown_increase,
                    policy.maximum_relative_drawdown_increase,
                    minimum=False,
                ),
                _relative_gate(
                    R4PromotionGateCode.RELATIVE_VOLATILITY,
                    reference,
                    None if evidence is None else evidence.relative_volatility_increase,
                    policy.maximum_relative_volatility_increase,
                    minimum=False,
                ),
                _relative_gate(
                    R4PromotionGateCode.RELATIVE_COST,
                    reference,
                    None if evidence is None else evidence.relative_cost_increase,
                    policy.maximum_relative_cost_increase,
                    minimum=False,
                ),
            )
        )
    return tuple(
        sorted(
            values,
            key=lambda item: (
                item.gate_code.value,
                item.reference_method.value if item.reference_method else "",
            ),
        )
    )


def _gate(
    code: R4PromotionGateCode,
    *,
    passes: bool,
    observed: Decimal,
    required: Decimal,
) -> R4PromotionGateOutcome:
    return R4PromotionGateOutcome(
        gate_code=code,
        reference_method=None,
        passes=passes,
        reason_code="" if passes else f"{code.value}_not_met",
        observed_value=observed,
        required_value=required,
    )


def _relative_gate(
    code: R4PromotionGateCode,
    reference: MacroRiskCandidateKind,
    observed: Decimal | None,
    required: Decimal,
    *,
    minimum: bool,
) -> R4PromotionGateOutcome:
    passes = observed is not None and (observed >= required if minimum else observed <= required)
    return R4PromotionGateOutcome(
        gate_code=code,
        reference_method=reference,
        passes=passes,
        reason_code="" if passes else f"{code.value}:{reference.value}_not_met",
        observed_value=observed,
        required_value=required,
    )


def _decision_payload(
    decision_id: str,
    decision_version: str,
    owner: str,
    capability: str,
    purpose: str,
    scope: R4PromotionScope,
    outcome: R4PromotionDecisionOutcome,
    policy: R4PromotionPolicy,
    trial: R4PromotionTrialSeal,
    relative: tuple[R4RelativeMethodEvidence, ...],
    gates: tuple[R4PromotionGateOutcome, ...],
    reason_codes: tuple[str, ...],
    decided_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r4-promotion-decision.v1",
        "identity": [decision_id, decision_version, owner, capability, purpose],
        "scope": [scope.scope_id, scope.content_hash],
        "outcome": outcome.value,
        "policy": [policy.policy_id, policy.policy_version, policy.content_hash],
        "trial": [trial.trial_id, trial.trial_version, trial.content_hash],
        "portfolio_record": [
            trial.portfolio_record.record_id,
            trial.portfolio_record.record_hash,
            trial.portfolio_record.content_hash,
        ],
        "current_r3": trial.current_r3_attestation.content_hash,
        "relative_method_evidence": [item.content_hash for item in relative],
        "gate_outcomes": [
            [
                item.gate_code.value,
                None if item.reference_method is None else item.reference_method.value,
                item.passes,
                item.reason_code,
                None if item.observed_value is None else _decimal_text(item.observed_value),
                _decimal_text(item.required_value),
            ]
            for item in gates
        ],
        "reason_codes": list(reason_codes),
        "window": [_utc_text(decided_at), _utc_text(recorded_at), _utc_text(valid_until)],
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r4_promotion_decision_hash(decision: R4PromotionDecision) -> str:
    """Recompute one exact derived R4 promotion decision hash."""

    return _hash_payload(
        _decision_payload(
            decision.decision_id,
            decision.decision_version,
            decision.owner,
            decision.capability,
            decision.purpose,
            decision.scope,
            decision.outcome,
            decision.policy,
            decision.trial,
            decision.relative_method_evidence,
            decision.gate_outcomes,
            decision.reason_codes,
            decision.decided_at,
            decision.recorded_at,
            decision.valid_until,
        )
    )


__all__ = [
    "R4PromotionDecision",
    "R4PromotionDecisionOutcome",
    "R4PromotionGateCode",
    "R4PromotionGateOutcome",
    "R4RelativeMethodEvidence",
    "create_r4_promotion_decision",
    "r4_promotion_decision_hash",
    "r4_promotion_decision_valid_until",
    "r4_relative_method_evidence_hash",
]
