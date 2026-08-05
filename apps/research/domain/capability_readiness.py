"""Fail-closed start gates for research capabilities with heavy data dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ResearchCapability(str, Enum):
    """Research capability whose implementation start is being evaluated."""

    INDUSTRY_EARNINGS_FORECAST = "industry_earnings_forecast"
    MARKET_STRUCTURE_INVESTOR_FLOW = "market_structure_investor_flow"
    MACRO_FACTOR_NOWCAST = "macro_factor_nowcast"
    MACRO_FACTOR_RISK_PARITY = "macro_factor_risk_parity"
    FIXED_INCOME_RELATIVE_VALUE = "fixed_income_relative_value"
    ADVANCED_STATE_MODEL = "advanced_state_model"
    SCENARIO_PROBABILITY_CALIBRATION = "scenario_probability_calibration"
    MULTI_ASSET_OPTIMIZATION = "multi_asset_optimization"


class ReadinessState(str, Enum):
    """State of one externally verifiable prerequisite."""

    VERIFIED = "verified"
    MISSING = "missing"
    UNVERIFIED = "unverified"
    STALE = "stale"


class ReadinessDecision(str, Enum):
    """Start decision produced by the readiness gate."""

    READY = "ready"
    BLOCKED = "blocked"


class ReadinessRequirement(str, Enum):
    """Stable prerequisite identifiers for the R1-R8 capability gates."""

    QUICK_WIN_USAGE_FEEDBACK = "quick_win_usage_feedback"
    AUDITABLE_OPERATING_FACT_SERIES = "auditable_operating_fact_series"
    FINANCIAL_PUBLICATION_PIT = "financial_publication_pit"
    VALUATION_PUBLICATION_PIT = "valuation_publication_pit"
    FORECAST_EVALUATION_SPEC = "forecast_evaluation_spec"
    RESEARCH_PROMOTION_GATE = "research_promotion_gate"
    FLOW_TAXONOMY_AND_UNITS = "flow_taxonomy_and_units"
    TWO_CYCLE_PIT_COVERAGE = "two_cycle_pit_coverage"
    PIT_ASSET_GROUP_MEMBERSHIP = "pit_asset_group_membership"
    PROXY_LABELLING = "proxy_labelling"
    MEASURE_SEMANTICS = "measure_semantics"

    TARGET_MACRO_VINTAGES_PIT = "target_macro_vintages_pit"
    PROXY_ASSET_PRICES_PIT = "proxy_asset_prices_pit"
    MACRO_RELEASE_CALENDAR = "macro_release_calendar"
    CONTINUOUS_FUTURES_POLICY = "continuous_futures_policy"
    EXPERIMENT_REGISTRY = "experiment_registry"
    MULTIPLE_TEST_FAMILY = "multiple_test_family"
    PROMOTION_DECISION = "promotion_decision"
    SPLIT_AND_EMBARGO_POLICY = "split_and_embargo_policy"
    MACRO_FACTOR_BENCHMARK = "macro_factor_benchmark"
    MACRO_FACTOR_COST_MODEL = "macro_factor_cost_model"
    R3_PROMOTED_FACTOR_VERSION = "r3_promoted_factor_version"
    PORTFOLIO_ASSET_EXPOSURES = "portfolio_asset_exposures"
    PORTFOLIO_COVARIANCE_INPUT = "portfolio_covariance_input"
    PORTFOLIO_WEIGHT_BOUNDS = "portfolio_weight_bounds"
    PORTFOLIO_TURNOVER_CONSTRAINT = "portfolio_turnover_constraint"
    PORTFOLIO_LIQUIDITY_CONSTRAINT = "portfolio_liquidity_constraint"
    EQUAL_WEIGHT_BENCHMARK = "equal_weight_benchmark"
    ASSET_RISK_PARITY_BENCHMARK = "asset_risk_parity_benchmark"
    PUBLICATION_GATE_AVAILABLE = "publication_gate_available"
    TWO_RELIABLE_CURVES_PUBLISHED = "two_reliable_curves_published"
    CREDIT_VALUATION_PUBLISHED = "credit_valuation_published"
    BOND_MASTER_COMPLETE = "bond_master_complete"
    CASH_FLOW_SCHEDULE_COMPLETE = "cash_flow_schedule_complete"
    FIXED_INCOME_TRADING_CALENDAR = "fixed_income_trading_calendar"
    DURATION_CONVEXITY_RECONCILED = "duration_convexity_reconciled"
    FIXED_INCOME_RESEARCH_ONLY_SCOPE = "fixed_income_research_only_scope"
    SIMPLE_REGIME_BASELINE = "simple_regime_baseline"
    SIMPLE_BASELINE_SHORTFALL_PROVEN = "simple_baseline_shortfall_proven"
    STATE_MODEL_PIT_INPUTS = "state_model_pit_inputs"
    STABLE_STATE_LABEL_PROTOCOL = "stable_state_label_protocol"
    OOS_TRANSITION_BENCHMARK = "oos_transition_benchmark"
    POLICY_REACTION_TARGET_CONTRACT = "policy_reaction_target_contract"
    GOVERNED_SCENARIO_VERSIONS = "governed_scenario_versions"
    APPEND_ONLY_FORECAST_LEDGER = "append_only_forecast_ledger"
    SCENARIO_VERSION_LEDGER_BINDING = "scenario_version_ledger_binding"
    SUBJECTIVE_MODEL_PROBABILITY_SEPARATION = "subjective_model_probability_separation"
    COMPLETE_SCENARIO_OUTCOME_HISTORY = "complete_scenario_outcome_history"
    CALIBRATION_SAMPLE_POLICY = "calibration_sample_policy"
    HISTORICAL_ANALOGY_PIT_MANIFEST = "historical_analogy_pit_manifest"
    PORTFOLIO_PLANNING_CONSTRAINTS = "portfolio_planning_constraints"
    RISK_CENTER_SCENARIO_INPUT = "risk_center_scenario_input"
    PORTFOLIO_CANONICAL_SNAPSHOT = "portfolio_canonical_snapshot"
    R4_PROMOTED_MACRO_RISK_VERSION = "r4_promoted_macro_risk_version"
    R5_PROMOTED_FIXED_INCOME_VERSION = "r5_promoted_fixed_income_version"
    EXECUTION_FEEDBACK_RECONCILED = "execution_feedback_reconciled"
    OPTIMIZER_INPUT_CONTRACT = "optimizer_input_contract"
    OPTIMIZER_BASELINE_FAIL_CLOSED_POLICY = "optimizer_baseline_fail_closed_policy"


R1_REQUIREMENTS: tuple[ReadinessRequirement, ...] = (
    ReadinessRequirement.QUICK_WIN_USAGE_FEEDBACK,
    ReadinessRequirement.AUDITABLE_OPERATING_FACT_SERIES,
    ReadinessRequirement.FINANCIAL_PUBLICATION_PIT,
    ReadinessRequirement.VALUATION_PUBLICATION_PIT,
    ReadinessRequirement.FORECAST_EVALUATION_SPEC,
    ReadinessRequirement.RESEARCH_PROMOTION_GATE,
)

R2_REQUIREMENTS: tuple[ReadinessRequirement, ...] = (
    ReadinessRequirement.FLOW_TAXONOMY_AND_UNITS,
    ReadinessRequirement.TWO_CYCLE_PIT_COVERAGE,
    ReadinessRequirement.PIT_ASSET_GROUP_MEMBERSHIP,
    ReadinessRequirement.PROXY_LABELLING,
    ReadinessRequirement.MEASURE_SEMANTICS,
)


R3_REQUIREMENTS: tuple[ReadinessRequirement, ...] = (
    ReadinessRequirement.TARGET_MACRO_VINTAGES_PIT,
    ReadinessRequirement.PROXY_ASSET_PRICES_PIT,
    ReadinessRequirement.MACRO_RELEASE_CALENDAR,
    ReadinessRequirement.CONTINUOUS_FUTURES_POLICY,
    ReadinessRequirement.EXPERIMENT_REGISTRY,
    ReadinessRequirement.MULTIPLE_TEST_FAMILY,
    ReadinessRequirement.PROMOTION_DECISION,
    ReadinessRequirement.SPLIT_AND_EMBARGO_POLICY,
    ReadinessRequirement.MACRO_FACTOR_BENCHMARK,
    ReadinessRequirement.MACRO_FACTOR_COST_MODEL,
)

R4_REQUIREMENTS: tuple[ReadinessRequirement, ...] = (
    ReadinessRequirement.R3_PROMOTED_FACTOR_VERSION,
    ReadinessRequirement.PORTFOLIO_ASSET_EXPOSURES,
    ReadinessRequirement.PORTFOLIO_COVARIANCE_INPUT,
    ReadinessRequirement.MACRO_FACTOR_COST_MODEL,
    ReadinessRequirement.PORTFOLIO_WEIGHT_BOUNDS,
    ReadinessRequirement.PORTFOLIO_TURNOVER_CONSTRAINT,
    ReadinessRequirement.PORTFOLIO_LIQUIDITY_CONSTRAINT,
    ReadinessRequirement.EQUAL_WEIGHT_BENCHMARK,
    ReadinessRequirement.ASSET_RISK_PARITY_BENCHMARK,
)

R5_REQUIREMENTS: tuple[ReadinessRequirement, ...] = (
    ReadinessRequirement.PUBLICATION_GATE_AVAILABLE,
    ReadinessRequirement.TWO_RELIABLE_CURVES_PUBLISHED,
    ReadinessRequirement.CREDIT_VALUATION_PUBLISHED,
    ReadinessRequirement.BOND_MASTER_COMPLETE,
    ReadinessRequirement.CASH_FLOW_SCHEDULE_COMPLETE,
    ReadinessRequirement.FIXED_INCOME_TRADING_CALENDAR,
    ReadinessRequirement.DURATION_CONVEXITY_RECONCILED,
    ReadinessRequirement.FIXED_INCOME_RESEARCH_ONLY_SCOPE,
)

R6_REQUIREMENTS: tuple[ReadinessRequirement, ...] = (
    ReadinessRequirement.SIMPLE_REGIME_BASELINE,
    ReadinessRequirement.SIMPLE_BASELINE_SHORTFALL_PROVEN,
    ReadinessRequirement.STATE_MODEL_PIT_INPUTS,
    ReadinessRequirement.STABLE_STATE_LABEL_PROTOCOL,
    ReadinessRequirement.OOS_TRANSITION_BENCHMARK,
    ReadinessRequirement.POLICY_REACTION_TARGET_CONTRACT,
)

R7_REQUIREMENTS: tuple[ReadinessRequirement, ...] = (
    ReadinessRequirement.GOVERNED_SCENARIO_VERSIONS,
    ReadinessRequirement.APPEND_ONLY_FORECAST_LEDGER,
    ReadinessRequirement.SCENARIO_VERSION_LEDGER_BINDING,
    ReadinessRequirement.SUBJECTIVE_MODEL_PROBABILITY_SEPARATION,
    ReadinessRequirement.COMPLETE_SCENARIO_OUTCOME_HISTORY,
    ReadinessRequirement.CALIBRATION_SAMPLE_POLICY,
    ReadinessRequirement.HISTORICAL_ANALOGY_PIT_MANIFEST,
)

R8_REQUIREMENTS: tuple[ReadinessRequirement, ...] = (
    ReadinessRequirement.PORTFOLIO_PLANNING_CONSTRAINTS,
    ReadinessRequirement.RISK_CENTER_SCENARIO_INPUT,
    ReadinessRequirement.PORTFOLIO_CANONICAL_SNAPSHOT,
    ReadinessRequirement.R3_PROMOTED_FACTOR_VERSION,
    ReadinessRequirement.R4_PROMOTED_MACRO_RISK_VERSION,
    ReadinessRequirement.R5_PROMOTED_FIXED_INCOME_VERSION,
    ReadinessRequirement.EXECUTION_FEEDBACK_RECONCILED,
    ReadinessRequirement.OPTIMIZER_INPUT_CONTRACT,
    ReadinessRequirement.OPTIMIZER_BASELINE_FAIL_CLOSED_POLICY,
)

_REQUIREMENT_OWNERS: dict[ReadinessRequirement, str] = {
    ReadinessRequirement.QUICK_WIN_USAGE_FEEDBACK: "risk_center",
    ReadinessRequirement.AUDITABLE_OPERATING_FACT_SERIES: "data_center",
    ReadinessRequirement.FINANCIAL_PUBLICATION_PIT: "data_center",
    ReadinessRequirement.VALUATION_PUBLICATION_PIT: "data_center",
    ReadinessRequirement.FORECAST_EVALUATION_SPEC: "equity",
    ReadinessRequirement.RESEARCH_PROMOTION_GATE: "research",
    ReadinessRequirement.FLOW_TAXONOMY_AND_UNITS: "data_center",
    ReadinessRequirement.TWO_CYCLE_PIT_COVERAGE: "data_center",
    ReadinessRequirement.PIT_ASSET_GROUP_MEMBERSHIP: "data_center",
    ReadinessRequirement.PROXY_LABELLING: "data_center",
    ReadinessRequirement.MEASURE_SEMANTICS: "data_center",
    ReadinessRequirement.TARGET_MACRO_VINTAGES_PIT: "data_center",
    ReadinessRequirement.PROXY_ASSET_PRICES_PIT: "data_center",
    ReadinessRequirement.MACRO_RELEASE_CALENDAR: "data_center",
    ReadinessRequirement.CONTINUOUS_FUTURES_POLICY: "data_center",
    ReadinessRequirement.EXPERIMENT_REGISTRY: "research",
    ReadinessRequirement.MULTIPLE_TEST_FAMILY: "research",
    ReadinessRequirement.PROMOTION_DECISION: "research",
    ReadinessRequirement.SPLIT_AND_EMBARGO_POLICY: "research",
    ReadinessRequirement.MACRO_FACTOR_BENCHMARK: "macro_factor",
    ReadinessRequirement.MACRO_FACTOR_COST_MODEL: "portfolio",
    ReadinessRequirement.R3_PROMOTED_FACTOR_VERSION: "research",
    ReadinessRequirement.PORTFOLIO_ASSET_EXPOSURES: "portfolio",
    ReadinessRequirement.PORTFOLIO_COVARIANCE_INPUT: "portfolio",
    ReadinessRequirement.PORTFOLIO_WEIGHT_BOUNDS: "portfolio",
    ReadinessRequirement.PORTFOLIO_TURNOVER_CONSTRAINT: "portfolio",
    ReadinessRequirement.PORTFOLIO_LIQUIDITY_CONSTRAINT: "portfolio",
    ReadinessRequirement.EQUAL_WEIGHT_BENCHMARK: "macro_factor",
    ReadinessRequirement.ASSET_RISK_PARITY_BENCHMARK: "macro_factor",
    ReadinessRequirement.PUBLICATION_GATE_AVAILABLE: "data_center",
    ReadinessRequirement.TWO_RELIABLE_CURVES_PUBLISHED: "data_center",
    ReadinessRequirement.CREDIT_VALUATION_PUBLISHED: "data_center",
    ReadinessRequirement.BOND_MASTER_COMPLETE: "data_center",
    ReadinessRequirement.CASH_FLOW_SCHEDULE_COMPLETE: "data_center",
    ReadinessRequirement.FIXED_INCOME_TRADING_CALENDAR: "data_center",
    ReadinessRequirement.DURATION_CONVEXITY_RECONCILED: "fixed_income",
    ReadinessRequirement.FIXED_INCOME_RESEARCH_ONLY_SCOPE: "fixed_income",
    ReadinessRequirement.SIMPLE_REGIME_BASELINE: "regime",
    ReadinessRequirement.SIMPLE_BASELINE_SHORTFALL_PROVEN: "research",
    ReadinessRequirement.STATE_MODEL_PIT_INPUTS: "data_center",
    ReadinessRequirement.STABLE_STATE_LABEL_PROTOCOL: "research",
    ReadinessRequirement.OOS_TRANSITION_BENCHMARK: "research",
    ReadinessRequirement.POLICY_REACTION_TARGET_CONTRACT: "policy",
    ReadinessRequirement.GOVERNED_SCENARIO_VERSIONS: "risk_center",
    ReadinessRequirement.APPEND_ONLY_FORECAST_LEDGER: "signal",
    ReadinessRequirement.SCENARIO_VERSION_LEDGER_BINDING: "signal",
    ReadinessRequirement.SUBJECTIVE_MODEL_PROBABILITY_SEPARATION: "risk_center",
    ReadinessRequirement.COMPLETE_SCENARIO_OUTCOME_HISTORY: "audit",
    ReadinessRequirement.CALIBRATION_SAMPLE_POLICY: "research",
    ReadinessRequirement.HISTORICAL_ANALOGY_PIT_MANIFEST: "data_center",
    ReadinessRequirement.PORTFOLIO_PLANNING_CONSTRAINTS: "portfolio",
    ReadinessRequirement.RISK_CENTER_SCENARIO_INPUT: "risk_center",
    ReadinessRequirement.PORTFOLIO_CANONICAL_SNAPSHOT: "portfolio",
    ReadinessRequirement.R4_PROMOTED_MACRO_RISK_VERSION: "research",
    ReadinessRequirement.R5_PROMOTED_FIXED_INCOME_VERSION: "research",
    ReadinessRequirement.EXECUTION_FEEDBACK_RECONCILED: "broker_execution",
    ReadinessRequirement.OPTIMIZER_INPUT_CONTRACT: "portfolio",
    ReadinessRequirement.OPTIMIZER_BASELINE_FAIL_CLOSED_POLICY: "research",
}


@dataclass(frozen=True)
class ReadinessEvidence:
    """Evidence supplied by the canonical owner of one prerequisite."""

    requirement: ReadinessRequirement
    owner: str
    state: ReadinessState
    observed_at: datetime
    valid_until: datetime | None = None
    evidence_ref: str | None = None
    blocking_reason: str | None = None

    def __post_init__(self) -> None:
        """Reject unverifiable, owner-confused, or clock-invalid evidence."""

        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("readiness evidence observed_at must be timezone-aware")
        if self.valid_until is not None:
            if self.valid_until.tzinfo is None or self.valid_until.utcoffset() is None:
                raise ValueError("readiness evidence valid_until must be timezone-aware")
            if self.valid_until <= self.observed_at:
                raise ValueError("readiness evidence valid_until must follow observed_at")
        expected_owner = requirement_owner(self.requirement)
        if self.owner != expected_owner:
            raise ValueError(f"{self.requirement.value} evidence must be owned by {expected_owner}")
        if self.state is ReadinessState.VERIFIED:
            if self.evidence_ref is None or not self.evidence_ref.strip():
                raise ValueError("verified readiness evidence requires evidence_ref")
            if self.valid_until is None:
                raise ValueError("verified readiness evidence requires valid_until")
            if self.blocking_reason is not None:
                raise ValueError("verified readiness evidence cannot contain a blocking reason")
        elif self.blocking_reason is None or not self.blocking_reason.strip():
            raise ValueError("non-verified readiness evidence requires a blocking reason")


@dataclass(frozen=True)
class ReadinessBlocker:
    """Stable fail-closed reason returned to planning and audit consumers."""

    requirement: ReadinessRequirement
    owner: str
    reason_code: str
    detail: str


@dataclass(frozen=True)
class CapabilityReadinessReport:
    """Immutable start decision and its complete prerequisite evidence."""

    capability: ResearchCapability
    contract_version: str
    evaluated_at: datetime
    decision: ReadinessDecision
    evidence: tuple[ReadinessEvidence, ...]
    blockers: tuple[ReadinessBlocker, ...]

    @property
    def can_start(self) -> bool:
        """Return whether implementation work may cross the start gate."""

        return self.decision is ReadinessDecision.READY


def requirements_for(
    capability: ResearchCapability,
) -> tuple[ReadinessRequirement, ...]:
    """Return the complete governed requirement set for a capability."""

    if capability is ResearchCapability.INDUSTRY_EARNINGS_FORECAST:
        return R1_REQUIREMENTS
    if capability is ResearchCapability.MARKET_STRUCTURE_INVESTOR_FLOW:
        return R2_REQUIREMENTS
    if capability is ResearchCapability.MACRO_FACTOR_NOWCAST:
        return R3_REQUIREMENTS
    if capability is ResearchCapability.MACRO_FACTOR_RISK_PARITY:
        return R4_REQUIREMENTS
    if capability is ResearchCapability.FIXED_INCOME_RELATIVE_VALUE:
        return R5_REQUIREMENTS
    if capability is ResearchCapability.ADVANCED_STATE_MODEL:
        return R6_REQUIREMENTS
    if capability is ResearchCapability.SCENARIO_PROBABILITY_CALIBRATION:
        return R7_REQUIREMENTS
    if capability is ResearchCapability.MULTI_ASSET_OPTIMIZATION:
        return R8_REQUIREMENTS
    raise ValueError(f"unsupported research capability: {capability}")


def requirement_owner(requirement: ReadinessRequirement) -> str:
    """Return the canonical owner that must attest one requirement."""

    return _REQUIREMENT_OWNERS[requirement]


def evaluate_capability_readiness(
    *,
    capability: ResearchCapability,
    evaluated_at: datetime,
    evidence: tuple[ReadinessEvidence, ...],
) -> CapabilityReadinessReport:
    """Evaluate a capability without inferring missing prerequisites as ready."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("readiness evaluated_at must be timezone-aware")
    required = requirements_for(capability)
    required_set = set(required)
    supplied: dict[ReadinessRequirement, ReadinessEvidence] = {}
    for provided in evidence:
        if provided.requirement not in required_set:
            raise ValueError(f"unexpected readiness evidence for {provided.requirement.value}")
        if provided.requirement in supplied:
            raise ValueError(f"duplicate readiness evidence for {provided.requirement.value}")
        if provided.observed_at > evaluated_at:
            raise ValueError("readiness evidence cannot be observed in the future")
        if (
            provided.state is ReadinessState.VERIFIED
            and provided.valid_until is not None
            and provided.valid_until <= evaluated_at
        ):
            provided = ReadinessEvidence(
                requirement=provided.requirement,
                owner=provided.owner,
                state=ReadinessState.STALE,
                observed_at=provided.observed_at,
                valid_until=provided.valid_until,
                evidence_ref=provided.evidence_ref,
                blocking_reason=(
                    f"{capability.value}.{provided.requirement.value}.evidence_expired"
                ),
            )
        supplied[provided.requirement] = provided

    normalized: list[ReadinessEvidence] = []
    blockers: list[ReadinessBlocker] = []
    for requirement in required:
        candidate = supplied.get(requirement)
        if candidate is None:
            reason = f"{capability.value}.{requirement.value}.missing"
            candidate = ReadinessEvidence(
                requirement=requirement,
                owner=requirement_owner(requirement),
                state=ReadinessState.MISSING,
                observed_at=evaluated_at,
                blocking_reason=reason,
            )
        normalized.append(candidate)
        if candidate.state is not ReadinessState.VERIFIED:
            assert candidate.blocking_reason is not None
            blockers.append(
                ReadinessBlocker(
                    requirement=requirement,
                    owner=candidate.owner,
                    reason_code=(f"{capability.value}.{requirement.value}.{candidate.state.value}"),
                    detail=candidate.blocking_reason,
                )
            )

    decision = ReadinessDecision.BLOCKED if blockers else ReadinessDecision.READY
    return CapabilityReadinessReport(
        capability=capability,
        contract_version="research-capability-readiness.v1",
        evaluated_at=evaluated_at,
        decision=decision,
        evidence=tuple(normalized),
        blockers=tuple(blockers),
    )
