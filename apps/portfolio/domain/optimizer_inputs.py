"""Fail-closed contracts for governed multi-asset optimization inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OptimizationInputKind(str, Enum):
    """Typed inputs that may participate in a governed optimization problem."""

    EXPECTED_RETURN = "expected_return"
    MACRO_EXPOSURE = "macro_exposure"
    ASSET_COVARIANCE = "asset_covariance"
    SCENARIO_LOSS = "scenario_loss"
    DRAWDOWN_RISK_BUDGET = "drawdown_risk_budget"
    TRANSACTION_COST = "transaction_cost"
    TURNOVER_LIMIT = "turnover_limit"
    LIQUIDITY_LIMIT = "liquidity_limit"
    POSITION_BOUNDS = "position_bounds"
    TRADING_CONSTRAINTS = "trading_constraints"
    MANUAL_RESTRICTIONS = "manual_restrictions"
    CASH_REQUIREMENT = "cash_requirement"
    EXECUTION_FEEDBACK = "execution_feedback"


class OptimizationEvidenceState(str, Enum):
    """Decision-safety state of one canonical optimization input."""

    VERIFIED = "verified"
    MISSING = "missing"
    UNVERIFIED = "unverified"
    STALE = "stale"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class OptimizationInputRequirement:
    """One owner-bound requirement in a versioned optimizer input contract."""

    kind: OptimizationInputKind
    canonical_owner: str

    def __post_init__(self) -> None:
        """Reject requirements without an accountable owner."""

        if not self.canonical_owner.strip():
            raise ValueError("optimization input canonical_owner is required")


@dataclass(frozen=True)
class OptimizerInputContract:
    """Versioned input and upstream-promotion requirements for one methodology."""

    contract_version: str
    methodology: str
    requirements: tuple[OptimizationInputRequirement, ...]
    required_promotion_keys: tuple[str, ...]
    activated_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Validate uniqueness and the contract activation window."""

        if not self.contract_version.strip() or not self.methodology.strip():
            raise ValueError("optimizer contract version and methodology are required")
        _require_aware(self.activated_at, "activated_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until <= self.activated_at:
            raise ValueError("optimizer contract valid_until must follow activated_at")
        kinds = [item.kind for item in self.requirements]
        if not kinds:
            raise ValueError("optimizer contract requires at least one input")
        if len(kinds) != len(set(kinds)):
            raise ValueError("optimizer contract contains duplicate input kinds")
        if any(not key.strip() for key in self.required_promotion_keys):
            raise ValueError("optimizer promotion keys cannot be empty")
        if len(self.required_promotion_keys) != len(set(self.required_promotion_keys)):
            raise ValueError("optimizer contract contains duplicate promotion keys")


@dataclass(frozen=True)
class OptimizationInputEvidence:
    """Versioned evidence for one input without embedding its numerical payload."""

    kind: OptimizationInputKind
    owner: str
    state: OptimizationEvidenceState
    observed_at: datetime
    valid_until: datetime | None = None
    version: str | None = None
    evidence_ref: str | None = None
    content_hash: str | None = None
    universe_hash: str | None = None
    blocking_reason: str | None = None

    def __post_init__(self) -> None:
        """Reject unauditable or internally inconsistent evidence."""

        if not self.owner.strip():
            raise ValueError("optimization input owner is required")
        _require_aware(self.observed_at, "observed_at")
        if self.valid_until is not None:
            _require_aware(self.valid_until, "valid_until")
            if self.valid_until <= self.observed_at:
                raise ValueError("input valid_until must follow observed_at")
        if self.state is OptimizationEvidenceState.VERIFIED:
            required_values = (
                self.version,
                self.evidence_ref,
                self.content_hash,
                self.universe_hash,
            )
            if any(value is None or not value.strip() for value in required_values):
                raise ValueError("verified optimization input requires versioned evidence")
            if self.valid_until is None:
                raise ValueError("verified optimization input requires valid_until")
            if self.blocking_reason is not None:
                raise ValueError("verified optimization input cannot contain a blocker")
        elif self.blocking_reason is None or not self.blocking_reason.strip():
            raise ValueError("non-verified optimization input requires a blocker")


@dataclass(frozen=True)
class PromotionReference:
    """Approved upstream research version required by an optimizer contract."""

    capability_key: str
    version: str
    decision_ref: str
    approved_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Validate the immutable promotion reference and review window."""

        if any(
            not value.strip() for value in (self.capability_key, self.version, self.decision_ref)
        ):
            raise ValueError("promotion reference fields are required")
        _require_aware(self.approved_at, "approved_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until <= self.approved_at:
            raise ValueError("promotion valid_until must follow approved_at")


@dataclass(frozen=True)
class OptimizerInputBundle:
    """Immutable references assembled for one research optimization preview."""

    bundle_id: str
    contract_version: str
    portfolio_snapshot_id: str
    decision_snapshot_id: str
    universe_hash: str
    evaluated_at: datetime
    evidence: tuple[OptimizationInputEvidence, ...]
    promotions: tuple[PromotionReference, ...]

    def __post_init__(self) -> None:
        """Validate bundle identifiers and evaluation time."""

        if any(
            not value.strip()
            for value in (
                self.bundle_id,
                self.contract_version,
                self.portfolio_snapshot_id,
                self.decision_snapshot_id,
                self.universe_hash,
            )
        ):
            raise ValueError("optimizer input bundle identifiers are required")
        _require_aware(self.evaluated_at, "evaluated_at")


@dataclass(frozen=True)
class OptimizerInputBlocker:
    """Stable blocker preventing research optimization from starting."""

    reason_code: str
    detail: str
    owner: str
    input_kind: OptimizationInputKind | None = None
    promotion_key: str | None = None


@dataclass(frozen=True)
class OptimizerInputReadiness:
    """Fail-closed validation result for one optimizer input bundle."""

    bundle_id: str
    contract_version: str
    can_run_research_preview: bool
    must_not_execute: bool
    evidence: tuple[OptimizationInputEvidence, ...]
    promotions: tuple[PromotionReference, ...]
    blockers: tuple[OptimizerInputBlocker, ...]


def evaluate_optimizer_input_bundle(
    *,
    contract: OptimizerInputContract,
    bundle: OptimizerInputBundle,
) -> OptimizerInputReadiness:
    """Validate exact owner, freshness, universe, and promotion dependencies."""

    if bundle.contract_version != contract.contract_version:
        raise ValueError("optimizer bundle contract version mismatch")
    if bundle.evaluated_at < contract.activated_at:
        raise ValueError("optimizer contract is not active at evaluated_at")

    requirements = {item.kind: item for item in contract.requirements}
    supplied: dict[OptimizationInputKind, OptimizationInputEvidence] = {}
    for evidence in bundle.evidence:
        requirement = requirements.get(evidence.kind)
        if requirement is None:
            raise ValueError(f"unexpected optimization input: {evidence.kind.value}")
        if evidence.kind in supplied:
            raise ValueError(f"duplicate optimization input: {evidence.kind.value}")
        if evidence.owner != requirement.canonical_owner:
            raise ValueError(
                f"{evidence.kind.value} evidence must be owned by " f"{requirement.canonical_owner}"
            )
        if evidence.observed_at > bundle.evaluated_at:
            raise ValueError("optimization input cannot be observed in the future")
        supplied[evidence.kind] = _normalize_input_state(
            evidence=evidence,
            evaluated_at=bundle.evaluated_at,
            expected_universe_hash=bundle.universe_hash,
        )

    normalized: list[OptimizationInputEvidence] = []
    blockers: list[OptimizerInputBlocker] = []
    for requirement in contract.requirements:
        candidate = supplied.get(requirement.kind)
        if candidate is None:
            reason_code = f"optimizer_input.{requirement.kind.value}.missing"
            candidate = OptimizationInputEvidence(
                kind=requirement.kind,
                owner=requirement.canonical_owner,
                state=OptimizationEvidenceState.MISSING,
                observed_at=bundle.evaluated_at,
                blocking_reason=reason_code,
            )
        normalized.append(candidate)
        if candidate.state is not OptimizationEvidenceState.VERIFIED:
            assert candidate.blocking_reason is not None
            blockers.append(
                OptimizerInputBlocker(
                    reason_code=(f"optimizer_input.{candidate.kind.value}.{candidate.state.value}"),
                    detail=candidate.blocking_reason,
                    owner=candidate.owner,
                    input_kind=candidate.kind,
                )
            )

    promotions = _validate_promotions(
        contract=contract,
        bundle=bundle,
        blockers=blockers,
    )
    if contract.valid_until <= bundle.evaluated_at:
        blockers.append(
            OptimizerInputBlocker(
                reason_code="optimizer_input.contract.stale",
                detail="optimizer input contract has expired",
                owner="portfolio",
            )
        )

    return OptimizerInputReadiness(
        bundle_id=bundle.bundle_id,
        contract_version=contract.contract_version,
        can_run_research_preview=not blockers,
        must_not_execute=True,
        evidence=tuple(normalized),
        promotions=promotions,
        blockers=tuple(blockers),
    )


def _normalize_input_state(
    *,
    evidence: OptimizationInputEvidence,
    evaluated_at: datetime,
    expected_universe_hash: str,
) -> OptimizationInputEvidence:
    if evidence.state is not OptimizationEvidenceState.VERIFIED:
        return evidence
    assert evidence.valid_until is not None
    if evidence.valid_until <= evaluated_at:
        return _blocked_copy(
            evidence=evidence,
            state=OptimizationEvidenceState.STALE,
            reason="verified optimization input has expired",
        )
    if evidence.universe_hash != expected_universe_hash:
        return _blocked_copy(
            evidence=evidence,
            state=OptimizationEvidenceState.CONFLICT,
            reason="optimization input universe does not match the portfolio universe",
        )
    return evidence


def _blocked_copy(
    *,
    evidence: OptimizationInputEvidence,
    state: OptimizationEvidenceState,
    reason: str,
) -> OptimizationInputEvidence:
    return OptimizationInputEvidence(
        kind=evidence.kind,
        owner=evidence.owner,
        state=state,
        observed_at=evidence.observed_at,
        valid_until=evidence.valid_until,
        version=evidence.version,
        evidence_ref=evidence.evidence_ref,
        content_hash=evidence.content_hash,
        universe_hash=evidence.universe_hash,
        blocking_reason=reason,
    )


def _validate_promotions(
    *,
    contract: OptimizerInputContract,
    bundle: OptimizerInputBundle,
    blockers: list[OptimizerInputBlocker],
) -> tuple[PromotionReference, ...]:
    supplied: dict[str, PromotionReference] = {}
    required = set(contract.required_promotion_keys)
    for promotion in bundle.promotions:
        if promotion.capability_key not in required:
            raise ValueError(f"unexpected optimizer promotion: {promotion.capability_key}")
        if promotion.capability_key in supplied:
            raise ValueError(f"duplicate optimizer promotion: {promotion.capability_key}")
        if promotion.approved_at > bundle.evaluated_at:
            raise ValueError("optimizer promotion cannot be approved in the future")
        supplied[promotion.capability_key] = promotion

    normalized: list[PromotionReference] = []
    for key in contract.required_promotion_keys:
        candidate = supplied.get(key)
        if candidate is None:
            blockers.append(
                OptimizerInputBlocker(
                    reason_code=f"optimizer_input.promotion.{key}.missing",
                    detail=f"required promotion {key} is missing",
                    owner="research",
                    promotion_key=key,
                )
            )
            continue
        normalized.append(candidate)
        if candidate.valid_until <= bundle.evaluated_at:
            blockers.append(
                OptimizerInputBlocker(
                    reason_code=f"optimizer_input.promotion.{key}.stale",
                    detail=f"required promotion {key} has expired",
                    owner="research",
                    promotion_key=key,
                )
            )
    return tuple(normalized)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
