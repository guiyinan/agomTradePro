"""Evidence-bound liquidity-premium and once-only cost contracts for R5."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from apps.fixed_income.domain.evidence import (
    EvidenceRole,
    ExactEvidence,
    canonical_hash,
    require_aware,
    require_finite,
    require_sha256,
    require_token,
)


class LiquidityMeasureRole(StrEnum):
    """Exact market, decomposition, and distinct cost evidence roles."""

    BID_ASK_BP = "bid_ask_bp"
    TURNOVER_RATIO = "turnover_ratio"
    QUOTE_AGE_SECONDS = "quote_age_seconds"
    ISSUE_SIZE = "issue_size"
    FUNDING_PRESSURE_BP = "funding_pressure_bp"
    MARKET_SPREAD_BP = "market_spread_bp"
    EXPECTED_CREDIT_LOSS_BP = "expected_credit_loss_bp"
    OPTION_COST_BP = "option_cost_bp"
    OTHER_SPREAD_BP = "other_spread_bp"
    FINANCING_CARRY_COST_BP = "financing_carry_cost_bp"
    TRANSACTION_COST_BP = "transaction_cost_bp"
    MARKET_IMPACT_COST_BP = "market_impact_cost_bp"
    LIQUIDATION_COST_BP = "liquidation_cost_bp"
    GROSS_RELATIVE_VALUE_BP = "gross_relative_value_bp"


_PREMIUM_DRIVER_ROLES = (
    LiquidityMeasureRole.BID_ASK_BP,
    LiquidityMeasureRole.FUNDING_PRESSURE_BP,
    LiquidityMeasureRole.ISSUE_SIZE,
    LiquidityMeasureRole.QUOTE_AGE_SECONDS,
    LiquidityMeasureRole.TURNOVER_RATIO,
)
_COST_ROLES = (
    LiquidityMeasureRole.FINANCING_CARRY_COST_BP,
    LiquidityMeasureRole.LIQUIDATION_COST_BP,
    LiquidityMeasureRole.MARKET_IMPACT_COST_BP,
    LiquidityMeasureRole.TRANSACTION_COST_BP,
)
_OWNER_MEASURE_ROLES = tuple(
    role for role in LiquidityMeasureRole if role is not LiquidityMeasureRole.QUOTE_AGE_SECONDS
)
_SIGNED_MEASURE_ROLES = {
    LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP,
    LiquidityMeasureRole.MARKET_SPREAD_BP,
    LiquidityMeasureRole.OTHER_SPREAD_BP,
}


class MarketSpreadSemantics(StrEnum):
    """Whether market spread contains liquidity compensation."""

    INCLUDES_LIQUIDITY_PREMIUM = "includes_liquidity_premium"
    EXCLUDES_LIQUIDITY_PREMIUM = "excludes_liquidity_premium"


class LiquidityCostBasis(StrEnum):
    """Versioned basis for the cost ledger."""

    GROSS_TRADED_NOTIONAL = "gross_traded_notional"


class LiquidityPremiumStatus(StrEnum):
    """Availability state for one research-only decomposition."""

    AVAILABLE = "available"
    BLOCKED = "blocked"


class LiquidityPremiumBlockerCode(StrEnum):
    """Stable fail-closed decomposition, freshness, and cost reasons."""

    INPUT_HASH_MISMATCH = "fixed_income.liquidity.input.hash_mismatch"
    POLICY_INACTIVE = "fixed_income.liquidity.policy.inactive"
    EVIDENCE_FROM_FUTURE = "fixed_income.liquidity.evidence.from_future"
    EVIDENCE_STALE = "fixed_income.liquidity.evidence.stale"
    MEASURE_MISSING = "fixed_income.liquidity.measure.missing"
    MEASURE_DUPLICATE = "fixed_income.liquidity.measure.duplicate"
    QUOTE_AGE_UNVERIFIABLE = "fixed_income.liquidity.quote_age.unverifiable"
    UNIT_MISMATCH = "fixed_income.liquidity.unit.mismatch"
    SUBJECT_MISMATCH = "fixed_income.liquidity.subject.mismatch"
    CURRENCY_MISMATCH = "fixed_income.liquidity.currency.mismatch"
    QUOTE_STALE = "fixed_income.liquidity.quote.stale"
    TURNOVER_GATE_FAILED = "fixed_income.liquidity.turnover.gate"
    ISSUE_SIZE_GATE_FAILED = "fixed_income.liquidity.issue_size.gate"
    NEGATIVE_PREMIUM_NOT_ALLOWED = "fixed_income.liquidity.premium.negative"
    MARKET_SPREAD_IDENTITY_FAILED = "fixed_income.liquidity.identity.market_spread"
    GROSS_COST_TREATMENT_MISMATCH = "fixed_income.liquidity.gross.cost_treatment"


@dataclass(frozen=True)
class LiquidityPremiumBlocker:
    """Stable liquidity-premium blocker."""

    code: LiquidityPremiumBlockerCode
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, LiquidityPremiumBlockerCode):
            raise ValueError("LiquidityPremiumBlocker.code is invalid")
        require_token(
            self.detail.replace(" ", "_"),
            "LiquidityPremiumBlocker.detail",
            maximum=240,
        )


@dataclass(frozen=True)
class LiquidityMeasure:
    """One owner measurement; quote age is deliberately not a stored measure."""

    subject_id: str
    currency: str
    role: LiquidityMeasureRole
    value: Decimal
    unit: str
    observed_at: datetime
    available_at: datetime
    record_hash: str
    publication: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.subject_id, "LiquidityMeasure.subject_id")
        require_token(self.currency, "LiquidityMeasure.currency", maximum=12)
        if not isinstance(self.role, LiquidityMeasureRole):
            raise ValueError("LiquidityMeasure.role is invalid")
        if self.role is LiquidityMeasureRole.QUOTE_AGE_SECONDS:
            raise ValueError("quote age must be derived from quote observed_at")
        require_finite(self.value, "LiquidityMeasure.value")
        if self.role not in _SIGNED_MEASURE_ROLES and self.value < 0:
            raise ValueError("this liquidity measure role cannot be negative")
        if self.role is LiquidityMeasureRole.TURNOVER_RATIO and self.value > Decimal("1"):
            raise ValueError("turnover ratio must be in [0, 1]")
        if self.role is LiquidityMeasureRole.ISSUE_SIZE and self.value <= 0:
            raise ValueError("issue size must be positive")
        require_token(self.unit, "LiquidityMeasure.unit", maximum=32)
        require_aware(self.observed_at, "LiquidityMeasure.observed_at")
        require_aware(self.available_at, "LiquidityMeasure.available_at")
        if self.available_at < self.observed_at:
            raise ValueError("liquidity available_at cannot precede observed_at")
        require_sha256(self.record_hash, "LiquidityMeasure.record_hash")
        if self.publication.role is not EvidenceRole.PUBLICATION:
            raise ValueError("liquidity measure requires Publication evidence")
        if (
            self.publication.subject_id != self.subject_id
            or self.publication.currency != self.currency
            or self.publication.curve_role != f"liquidity:{self.role.value}"
            or self.publication.observed_at != self.observed_at
            or self.publication.available_at != self.available_at
        ):
            raise ValueError("liquidity measure must match Publication identity/clocks/role")
        if (
            self.record_hash != self.publication.content_hash
            and self.record_hash not in self.publication.upstream_hashes
        ):
            raise ValueError("liquidity record hash is not bound by Publication provenance")

    @property
    def seal_hash(self) -> str:
        """Hash value, unit, source clocks, semantic role, and Publication seal."""

        return canonical_hash(
            {
                "subject_id": self.subject_id,
                "currency": self.currency,
                "role": self.role,
                "value": self.value,
                "unit": self.unit,
                "observed_at": self.observed_at,
                "available_at": self.available_at,
                "record_hash": self.record_hash,
                "publication_hash": self.publication.seal_hash,
            }
        )


@dataclass(frozen=True)
class LiquidityPremiumRule:
    """Explicit transformation from owner/derived evidence to premium bp."""

    measure_role: LiquidityMeasureRole
    expected_unit: str
    reference_value: Decimal
    coefficient_bp_per_unit: Decimal

    def __post_init__(self) -> None:
        if self.measure_role not in _PREMIUM_DRIVER_ROLES:
            raise ValueError("premium rule role is not a premium driver")
        require_token(self.expected_unit, "LiquidityPremiumRule.expected_unit", maximum=32)
        require_finite(self.reference_value, "LiquidityPremiumRule.reference_value")
        require_finite(
            self.coefficient_bp_per_unit,
            "LiquidityPremiumRule.coefficient_bp_per_unit",
        )


@dataclass(frozen=True)
class LiquidityCostRule:
    """Explicit once-only cost application on gross traded notional."""

    measure_role: LiquidityMeasureRole
    expected_unit: str
    cost_basis: LiquidityCostBasis
    quoted_horizon_days: int
    applied_horizon_days: int
    application_multiplier: Decimal
    already_in_gross_relative_value: bool

    def __post_init__(self) -> None:
        if self.measure_role not in _COST_ROLES:
            raise ValueError("liquidity cost rule role is invalid")
        require_token(self.expected_unit, "LiquidityCostRule.expected_unit", maximum=32)
        if self.cost_basis is not LiquidityCostBasis.GROSS_TRADED_NOTIONAL:
            raise ValueError("liquidity costs require gross traded notional basis")
        if self.quoted_horizon_days <= 0 or self.applied_horizon_days <= 0:
            raise ValueError("cost quoted/applied horizons must be positive")
        require_finite(self.application_multiplier, "application_multiplier")
        if self.application_multiplier <= 0:
            raise ValueError("cost application multiplier must be positive")


@dataclass(frozen=True)
class LiquidityPremiumPolicy:
    """Versioned decomposition, hard gates, and cost treatment semantics."""

    policy_id: str
    policy_version: str
    market_spread_semantics: MarketSpreadSemantics
    premium_rules: tuple[LiquidityPremiumRule, ...]
    cost_rules: tuple[LiquidityCostRule, ...]
    decomposition_tolerance_bp: Decimal
    maximum_quote_age_seconds: int
    minimum_turnover_ratio: Decimal
    minimum_issue_size: Decimal
    allow_negative_model_premium: bool
    allow_negative_market_implied_premium: bool
    gross_cost_treatment_version: str
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.policy_id, "LiquidityPremiumPolicy.policy_id")
        require_token(self.policy_version, "LiquidityPremiumPolicy.policy_version")
        if not isinstance(self.market_spread_semantics, MarketSpreadSemantics):
            raise ValueError("market spread semantics are invalid")
        require_token(
            self.gross_cost_treatment_version,
            "LiquidityPremiumPolicy.gross_cost_treatment_version",
        )
        premium_roles = tuple(rule.measure_role for rule in self.premium_rules)
        if premium_roles != tuple(sorted(_PREMIUM_DRIVER_ROLES, key=lambda role: role.value)):
            raise ValueError("premium rules must exactly cover canonical driver roles")
        cost_roles = tuple(rule.measure_role for rule in self.cost_rules)
        if cost_roles != tuple(sorted(_COST_ROLES, key=lambda role: role.value)):
            raise ValueError("cost rules must exactly cover canonical cost roles")
        for name in (
            "decomposition_tolerance_bp",
            "minimum_turnover_ratio",
            "minimum_issue_size",
        ):
            require_finite(getattr(self, name), f"LiquidityPremiumPolicy.{name}")
        if self.decomposition_tolerance_bp < 0:
            raise ValueError("decomposition tolerance cannot be negative")
        if self.maximum_quote_age_seconds <= 0:
            raise ValueError("maximum quote age must be positive")
        if not Decimal("0") <= self.minimum_turnover_ratio <= Decimal("1"):
            raise ValueError("minimum turnover ratio must be in [0, 1]")
        if self.minimum_issue_size <= 0:
            raise ValueError("minimum issue size must be positive")
        if self.evidence.role is not EvidenceRole.POLICY:
            raise ValueError("liquidity policy requires Research evidence")
        if (
            self.evidence.evidence_id != self.policy_id
            or self.evidence.version != self.policy_version
            or self.evidence.subject_id != self.policy_id
            or self.evidence.curve_role != "liquidity_premium_policy"
        ):
            raise ValueError("liquidity policy evidence identity mismatch")

    @property
    def policy_hash(self) -> str:
        """Hash all coefficients, units, hard gates, and cost semantics."""

        return canonical_hash(
            {
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "market_spread_semantics": self.market_spread_semantics,
                "premium_rules": self.premium_rules,
                "cost_rules": self.cost_rules,
                "decomposition_tolerance_bp": self.decomposition_tolerance_bp,
                "maximum_quote_age_seconds": self.maximum_quote_age_seconds,
                "minimum_turnover_ratio": self.minimum_turnover_ratio,
                "minimum_issue_size": self.minimum_issue_size,
                "allow_negative_model_premium": self.allow_negative_model_premium,
                "allow_negative_market_implied_premium": (
                    self.allow_negative_market_implied_premium
                ),
                "gross_cost_treatment_version": self.gross_cost_treatment_version,
                "evidence_hash": self.evidence.seal_hash,
            }
        )


@dataclass(frozen=True)
class LiquidityPremiumEvidence:
    """Exact measures plus owner-attested gross-value included-cost manifest."""

    evidence_id: str
    evidence_version: str
    subject_id: str
    currency: str
    measures: tuple[LiquidityMeasure, ...]
    gross_included_cost_roles: tuple[LiquidityMeasureRole, ...]
    gross_cost_treatment_version: str
    gross_inclusion_manifest_hash: str
    source: ExactEvidence

    def __post_init__(self) -> None:
        for name in (
            "evidence_id",
            "evidence_version",
            "subject_id",
            "currency",
            "gross_cost_treatment_version",
        ):
            require_token(str(getattr(self, name)), f"LiquidityPremiumEvidence.{name}")
        if self.source.role is not EvidenceRole.EXACT_PIT_INPUT:
            raise ValueError("liquidity premium requires exact PIT input evidence")
        if (
            self.source.evidence_id != self.evidence_id
            or self.source.version != self.evidence_version
            or self.source.subject_id != self.subject_id
            or self.source.currency != self.currency
            or self.source.curve_role != "liquidity_premium"
        ):
            raise ValueError("liquidity PIT source identity mismatch")
        if self.measures != tuple(sorted(self.measures, key=lambda item: item.role.value)):
            raise ValueError("liquidity measures must use canonical role order")
        included = tuple(sorted(set(self.gross_included_cost_roles), key=lambda role: role.value))
        if self.gross_included_cost_roles != included or any(
            role not in _COST_ROLES for role in included
        ):
            raise ValueError("gross included cost roles must be canonical valid costs")
        require_sha256(
            self.gross_inclusion_manifest_hash,
            "LiquidityPremiumEvidence.gross_inclusion_manifest_hash",
        )
        gross = next(
            (
                measure
                for measure in self.measures
                if measure.role is LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP
            ),
            None,
        )
        if gross is not None:
            expected_manifest = canonical_hash(
                {
                    "subject_id": gross.subject_id,
                    "currency": gross.currency,
                    "measure_role": gross.role,
                    "gross_record_hash": gross.record_hash,
                    "observed_at": gross.observed_at,
                    "available_at": gross.available_at,
                    "included_cost_roles": self.gross_included_cost_roles,
                    "treatment_version": self.gross_cost_treatment_version,
                }
            )
            if self.gross_inclusion_manifest_hash != expected_manifest:
                raise ValueError("gross included-cost manifest hash mismatch")
            if expected_manifest not in gross.publication.upstream_hashes:
                raise ValueError("gross Publication does not attest included-cost manifest")
        required_upstreams = {
            *(measure.seal_hash for measure in self.measures),
            self.gross_inclusion_manifest_hash,
        }
        if not required_upstreams.issubset(set(self.source.upstream_hashes)):
            raise ValueError("liquidity PIT source must attest all measures and gross manifest")

    @property
    def evidence_hash(self) -> str:
        """Hash every owner measure and the gross included-cost attestation."""

        return canonical_hash(
            {
                "evidence_id": self.evidence_id,
                "evidence_version": self.evidence_version,
                "subject_id": self.subject_id,
                "currency": self.currency,
                "measure_hashes": tuple(measure.seal_hash for measure in self.measures),
                "gross_included_cost_roles": self.gross_included_cost_roles,
                "gross_cost_treatment_version": self.gross_cost_treatment_version,
                "gross_inclusion_manifest_hash": self.gross_inclusion_manifest_hash,
                "source_hash": self.source.seal_hash,
            }
        )


@dataclass(frozen=True)
class LiquidityPremiumComponent:
    """Recomputable contribution of one distinct premium driver."""

    measure_role: LiquidityMeasureRole
    observed_unit: str
    observed_value: Decimal
    reference_value: Decimal
    coefficient_bp_per_unit: Decimal
    contribution_bp: Decimal

    def __post_init__(self) -> None:
        require_token(self.observed_unit, "LiquidityPremiumComponent.observed_unit")
        for name in (
            "observed_value",
            "reference_value",
            "coefficient_bp_per_unit",
            "contribution_bp",
        ):
            require_finite(getattr(self, name), f"LiquidityPremiumComponent.{name}")
        if self.measure_role not in _PREMIUM_DRIVER_ROLES:
            raise ValueError("premium output contains a non-driver role")
        if (
            self.contribution_bp
            != (self.observed_value - self.reference_value) * self.coefficient_bp_per_unit
        ):
            raise ValueError("premium contribution identity failed")


@dataclass(frozen=True)
class LiquidityCostEntry:
    """One exact cost with horizon/basis and once-only deduction."""

    measure_role: LiquidityMeasureRole
    quoted_unit: str
    quoted_cost_bp: Decimal
    cost_basis: LiquidityCostBasis
    quoted_horizon_days: int
    applied_horizon_days: int
    application_multiplier: Decimal
    applied_cost_bp: Decimal
    already_in_gross_relative_value: bool
    deductible_cost_bp: Decimal

    def __post_init__(self) -> None:
        require_token(self.quoted_unit, "LiquidityCostEntry.quoted_unit")
        for name in (
            "quoted_cost_bp",
            "application_multiplier",
            "applied_cost_bp",
            "deductible_cost_bp",
        ):
            require_finite(getattr(self, name), f"LiquidityCostEntry.{name}")
        if self.measure_role not in _COST_ROLES:
            raise ValueError("cost output role is invalid")
        if self.cost_basis is not LiquidityCostBasis.GROSS_TRADED_NOTIONAL:
            raise ValueError("cost output basis is invalid")
        if self.quoted_horizon_days <= 0 or self.applied_horizon_days <= 0:
            raise ValueError("cost output horizons must be positive")
        if (
            self.quoted_cost_bp < 0
            or self.application_multiplier <= 0
            or self.applied_cost_bp < 0
            or self.deductible_cost_bp < 0
        ):
            raise ValueError("cost values/multiplier cannot be negative or zero")
        if self.applied_cost_bp != self.quoted_cost_bp * self.application_multiplier:
            raise ValueError("applied liquidity cost is not recomputable")
        expected = Decimal("0") if self.already_in_gross_relative_value else self.applied_cost_bp
        if self.deductible_cost_bp != expected:
            raise ValueError("liquidity cost was omitted or deducted twice")


@dataclass(frozen=True)
class LiquidityPremiumAssessment:
    """Fully sealed premium decomposition and once-only cost ledger."""

    status: LiquidityPremiumStatus
    subject_id: str
    currency: str
    evaluated_at: datetime
    input_hash: str
    output_hash: str
    policy_hash: str
    market_spread_semantics: MarketSpreadSemantics
    premium_rules: tuple[LiquidityPremiumRule, ...]
    cost_rules: tuple[LiquidityCostRule, ...]
    decomposition_tolerance_bp: Decimal
    allow_negative_model_premium: bool
    allow_negative_market_implied_premium: bool
    maximum_quote_age_seconds: int
    minimum_turnover_ratio: Decimal
    minimum_issue_size: Decimal
    quote_observed_at: datetime | None
    quote_age_seconds: Decimal | None
    turnover_ratio: Decimal | None
    issue_size: Decimal | None
    gross_relative_value_bp: Decimal | None
    market_spread_bp: Decimal | None
    expected_credit_loss_bp: Decimal | None
    option_cost_bp: Decimal | None
    other_spread_bp: Decimal | None
    model_liquidity_premium_bp: Decimal | None
    market_implied_liquidity_premium_bp: Decimal | None
    premium_components: tuple[LiquidityPremiumComponent, ...]
    cost_entries: tuple[LiquidityCostEntry, ...]
    gross_included_cost_roles: tuple[LiquidityMeasureRole, ...]
    gross_cost_treatment_version: str
    gross_inclusion_manifest_hash: str
    total_deductible_cost_bp: Decimal | None
    net_relative_value_bp: Decimal | None
    missing_roles: tuple[LiquidityMeasureRole, ...]
    blockers: tuple[LiquidityPremiumBlocker, ...]
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        require_token(self.subject_id, "LiquidityPremiumAssessment.subject_id")
        require_token(self.currency, "LiquidityPremiumAssessment.currency")
        require_aware(self.evaluated_at, "LiquidityPremiumAssessment.evaluated_at")
        for name in (
            "input_hash",
            "output_hash",
            "policy_hash",
            "gross_inclusion_manifest_hash",
        ):
            require_sha256(str(getattr(self, name)), f"LiquidityPremiumAssessment.{name}")
        for name in (
            "decomposition_tolerance_bp",
            "minimum_turnover_ratio",
            "minimum_issue_size",
        ):
            require_finite(getattr(self, name), f"LiquidityPremiumAssessment.{name}")
        if not isinstance(self.market_spread_semantics, MarketSpreadSemantics):
            raise ValueError("assessment market spread semantics are invalid")
        if self.decomposition_tolerance_bp < 0:
            raise ValueError("assessment decomposition tolerance cannot be negative")
        if not Decimal("0") <= self.minimum_turnover_ratio <= Decimal("1"):
            raise ValueError("assessment minimum turnover must be in [0, 1]")
        if self.minimum_issue_size <= 0:
            raise ValueError("assessment minimum issue size must be positive")
        if self.quote_observed_at is not None:
            require_aware(self.quote_observed_at, "quote_observed_at")
        if (self.quote_observed_at is None) != (self.quote_age_seconds is None):
            raise ValueError("quote observed_at and derived age must be all-or-none")
        for name in (
            "quote_age_seconds",
            "turnover_ratio",
            "issue_size",
            "gross_relative_value_bp",
            "market_spread_bp",
            "expected_credit_loss_bp",
            "option_cost_bp",
            "other_spread_bp",
            "model_liquidity_premium_bp",
            "market_implied_liquidity_premium_bp",
            "total_deductible_cost_bp",
            "net_relative_value_bp",
        ):
            value = getattr(self, name)
            if value is not None:
                require_finite(value, f"LiquidityPremiumAssessment.{name}")
        if self.quote_age_seconds is not None and self.quote_age_seconds < 0:
            raise ValueError("quote age cannot be negative")
        if self.turnover_ratio is not None and not Decimal("0") <= self.turnover_ratio <= Decimal(
            "1"
        ):
            raise ValueError("turnover ratio must be in [0, 1]")
        if self.issue_size is not None and self.issue_size <= 0:
            raise ValueError("issue size must be positive")
        if self.quote_observed_at is not None and self.quote_age_seconds != _elapsed_seconds(
            self.quote_observed_at,
            self.evaluated_at,
        ):
            raise ValueError("quote age is not recomputable from source observed_at")
        if not (self.research_only and self.must_not_execute and self.must_not_use_for_decision):
            raise ValueError("liquidity premium assessment must remain research-only")
        if self.maximum_quote_age_seconds <= 0:
            raise ValueError("maximum quote age must be positive")
        component_roles = tuple(item.measure_role for item in self.premium_components)
        rule_roles = tuple(rule.measure_role for rule in self.premium_rules)
        if rule_roles != tuple(sorted(_PREMIUM_DRIVER_ROLES, key=lambda role: role.value)):
            raise ValueError("assessment premium rules do not cover exact driver universe")
        if component_roles != tuple(
            sorted(set(component_roles), key=lambda role: role.value)
        ) or any(role not in rule_roles for role in component_roles):
            raise ValueError("premium components must be a canonical driver subset")
        premium_rule_by_role = {rule.measure_role: rule for rule in self.premium_rules}
        if any(
            component.observed_unit != premium_rule_by_role[component.measure_role].expected_unit
            or component.reference_value
            != premium_rule_by_role[component.measure_role].reference_value
            or component.coefficient_bp_per_unit
            != premium_rule_by_role[component.measure_role].coefficient_bp_per_unit
            for component in self.premium_components
        ):
            raise ValueError("premium components do not replay exact policy rules")
        component_values = {
            component.measure_role: component.observed_value
            for component in self.premium_components
        }
        if (
            LiquidityMeasureRole.QUOTE_AGE_SECONDS in component_values
            and component_values[LiquidityMeasureRole.QUOTE_AGE_SECONDS] != self.quote_age_seconds
        ):
            raise ValueError("quote-age driver differs from derived quote age")
        if (
            LiquidityMeasureRole.TURNOVER_RATIO in component_values
            and component_values[LiquidityMeasureRole.TURNOVER_RATIO] != self.turnover_ratio
        ):
            raise ValueError("turnover driver differs from owner top-level value")
        if (
            LiquidityMeasureRole.ISSUE_SIZE in component_values
            and component_values[LiquidityMeasureRole.ISSUE_SIZE] != self.issue_size
        ):
            raise ValueError("issue-size driver differs from owner top-level value")
        if self.model_liquidity_premium_bp is not None and (
            self.model_liquidity_premium_bp
            != sum(
                (item.contribution_bp for item in self.premium_components),
                start=Decimal("0"),
            )
        ):
            raise ValueError("model premium is not recomputable")
        cost_roles = tuple(item.measure_role for item in self.cost_entries)
        cost_rule_roles = tuple(rule.measure_role for rule in self.cost_rules)
        if cost_rule_roles != tuple(sorted(_COST_ROLES, key=lambda role: role.value)):
            raise ValueError("assessment cost rules do not cover exact cost universe")
        if cost_roles != tuple(sorted(set(cost_roles), key=lambda role: role.value)) or any(
            role not in cost_rule_roles for role in cost_roles
        ):
            raise ValueError("cost entries must be a canonical cost subset")
        cost_rule_by_role = {rule.measure_role: rule for rule in self.cost_rules}
        if any(
            entry.quoted_unit != cost_rule_by_role[entry.measure_role].expected_unit
            or entry.cost_basis is not cost_rule_by_role[entry.measure_role].cost_basis
            or entry.quoted_horizon_days
            != cost_rule_by_role[entry.measure_role].quoted_horizon_days
            or entry.applied_horizon_days
            != cost_rule_by_role[entry.measure_role].applied_horizon_days
            or entry.application_multiplier
            != cost_rule_by_role[entry.measure_role].application_multiplier
            or entry.already_in_gross_relative_value
            is not cost_rule_by_role[entry.measure_role].already_in_gross_relative_value
            for entry in self.cost_entries
        ):
            raise ValueError("cost entries do not replay exact policy rules")
        policy_included_roles = tuple(
            rule.measure_role for rule in self.cost_rules if rule.already_in_gross_relative_value
        )
        if policy_included_roles != self.gross_included_cost_roles:
            raise ValueError("gross owner manifest and cost ledger treatment differ")
        if self.total_deductible_cost_bp is not None and (
            self.total_deductible_cost_bp
            != sum(
                (item.deductible_cost_bp for item in self.cost_entries),
                start=Decimal("0"),
            )
        ):
            raise ValueError("deductible cost total is not recomputable")
        if self.net_relative_value_bp is not None and (
            self.gross_relative_value_bp is None
            or self.total_deductible_cost_bp is None
            or self.net_relative_value_bp
            != self.gross_relative_value_bp - self.total_deductible_cost_bp
        ):
            raise ValueError("net relative value is not recomputable")
        spread_values = (
            self.market_spread_bp,
            self.expected_credit_loss_bp,
            self.option_cost_bp,
            self.other_spread_bp,
        )
        if all(value is not None for value in spread_values):
            market = self.market_spread_bp or Decimal("0")
            credit = self.expected_credit_loss_bp or Decimal("0")
            option = self.option_cost_bp or Decimal("0")
            other = self.other_spread_bp or Decimal("0")
            residual = market - credit - option - other
            if self.market_spread_semantics is MarketSpreadSemantics.INCLUDES_LIQUIDITY_PREMIUM:
                if self.market_implied_liquidity_premium_bp != residual:
                    raise ValueError("market-implied liquidity premium is not recomputable")
                if (
                    self.model_liquidity_premium_bp is not None
                    and abs(residual - self.model_liquidity_premium_bp)
                    > self.decomposition_tolerance_bp
                ):
                    raise ValueError("market/model liquidity premium identity failed")
            else:
                if self.market_implied_liquidity_premium_bp is not None:
                    raise ValueError("excluded market spread cannot publish implied premium")
                if abs(residual) > self.decomposition_tolerance_bp:
                    raise ValueError("market spread excluding premium is not decomposed")
        if self.missing_roles != tuple(
            sorted(set(self.missing_roles), key=lambda role: role.value)
        ):
            raise ValueError("missing liquidity roles must be unique and canonical")
        if self.blockers != tuple(
            sorted(set(self.blockers), key=lambda item: (item.code.value, item.detail))
        ):
            raise ValueError("liquidity blockers must be unique and canonical")
        if self.status is LiquidityPremiumStatus.AVAILABLE:
            required = (
                self.quote_age_seconds,
                self.turnover_ratio,
                self.issue_size,
                self.gross_relative_value_bp,
                self.market_spread_bp,
                self.expected_credit_loss_bp,
                self.option_cost_bp,
                self.other_spread_bp,
                self.model_liquidity_premium_bp,
                self.total_deductible_cost_bp,
                self.net_relative_value_bp,
            )
            if (
                self.blockers
                or self.missing_roles
                or component_roles != rule_roles
                or cost_roles != cost_rule_roles
                or any(value is None for value in required)
            ):
                raise ValueError("available liquidity output is incomplete")
            if self.quote_age_seconds is not None and self.quote_age_seconds > Decimal(
                self.maximum_quote_age_seconds
            ):
                raise ValueError("available liquidity output violates quote-age gate")
            if (
                self.turnover_ratio is not None
                and self.turnover_ratio < self.minimum_turnover_ratio
            ):
                raise ValueError("available liquidity output violates turnover gate")
            if self.issue_size is not None and self.issue_size < self.minimum_issue_size:
                raise ValueError("available liquidity output violates issue-size gate")
            if (
                not self.allow_negative_model_premium
                and self.model_liquidity_premium_bp is not None
                and self.model_liquidity_premium_bp < 0
            ):
                raise ValueError("available negative model premium violates policy")
            if (
                not self.allow_negative_market_implied_premium
                and self.market_implied_liquidity_premium_bp is not None
                and self.market_implied_liquidity_premium_bp < 0
            ):
                raise ValueError("available negative implied premium violates policy")
        elif not self.blockers:
            raise ValueError("blocked liquidity output requires blockers")
        if self.output_hash != self.calculated_output_hash:
            raise ValueError("liquidity premium output hash mismatch")

    @property
    def calculated_output_hash(self) -> str:
        """Recompute the complete decomposition, gates, cost ledger, and safety seal."""

        return canonical_hash(
            {
                name: getattr(self, name)
                for name in self.__dataclass_fields__
                if name != "output_hash"
            }
        )


def liquidity_premium_input_hash(
    evidence: LiquidityPremiumEvidence,
    policy: LiquidityPremiumPolicy,
    *,
    evaluated_at: datetime,
) -> str:
    """Hash all exact measures, owner gross manifest, policy, and PIT cutoff."""

    require_aware(evaluated_at, "evaluated_at")
    return canonical_hash(
        {
            "evidence_hash": evidence.evidence_hash,
            "policy_hash": policy.policy_hash,
            "evaluated_at": evaluated_at,
        }
    )


def _elapsed_seconds(start: datetime, end: datetime) -> Decimal:
    delta = end - start
    return Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(
        "1000000"
    )


def _blocker(
    code: LiquidityPremiumBlockerCode,
    detail: str,
) -> LiquidityPremiumBlocker:
    return LiquidityPremiumBlocker(code=code, detail=detail)


def _make_result(
    *,
    status: LiquidityPremiumStatus,
    evidence: LiquidityPremiumEvidence,
    policy: LiquidityPremiumPolicy,
    evaluated_at: datetime,
    input_hash: str,
    values: dict[LiquidityMeasureRole, Decimal],
    quote_age_seconds: Decimal | None,
    components: tuple[LiquidityPremiumComponent, ...],
    costs: tuple[LiquidityCostEntry, ...],
    implied_premium: Decimal | None,
    missing_roles: tuple[LiquidityMeasureRole, ...],
    blockers: tuple[LiquidityPremiumBlocker, ...],
) -> LiquidityPremiumAssessment:
    model_premium = (
        sum((item.contribution_bp for item in components), start=Decimal("0"))
        if len(components) == len(_PREMIUM_DRIVER_ROLES)
        else None
    )
    total_cost = (
        sum((item.deductible_cost_bp for item in costs), start=Decimal("0"))
        if len(costs) == len(_COST_ROLES)
        else None
    )
    gross = values.get(LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP)
    net = gross - total_cost if gross is not None and total_cost is not None else None
    kwargs: dict[str, object] = {
        "status": status,
        "subject_id": evidence.subject_id,
        "currency": evidence.currency,
        "evaluated_at": evaluated_at,
        "input_hash": input_hash,
        "policy_hash": policy.policy_hash,
        "market_spread_semantics": policy.market_spread_semantics,
        "premium_rules": policy.premium_rules,
        "cost_rules": policy.cost_rules,
        "decomposition_tolerance_bp": policy.decomposition_tolerance_bp,
        "allow_negative_model_premium": policy.allow_negative_model_premium,
        "allow_negative_market_implied_premium": (policy.allow_negative_market_implied_premium),
        "maximum_quote_age_seconds": policy.maximum_quote_age_seconds,
        "minimum_turnover_ratio": policy.minimum_turnover_ratio,
        "minimum_issue_size": policy.minimum_issue_size,
        "quote_observed_at": (
            next(
                (
                    measure.observed_at
                    for measure in evidence.measures
                    if measure.role is LiquidityMeasureRole.BID_ASK_BP
                ),
                None,
            )
        ),
        "quote_age_seconds": quote_age_seconds,
        "turnover_ratio": values.get(LiquidityMeasureRole.TURNOVER_RATIO),
        "issue_size": values.get(LiquidityMeasureRole.ISSUE_SIZE),
        "gross_relative_value_bp": gross,
        "market_spread_bp": values.get(LiquidityMeasureRole.MARKET_SPREAD_BP),
        "expected_credit_loss_bp": values.get(LiquidityMeasureRole.EXPECTED_CREDIT_LOSS_BP),
        "option_cost_bp": values.get(LiquidityMeasureRole.OPTION_COST_BP),
        "other_spread_bp": values.get(LiquidityMeasureRole.OTHER_SPREAD_BP),
        "model_liquidity_premium_bp": model_premium,
        "market_implied_liquidity_premium_bp": implied_premium,
        "premium_components": components,
        "cost_entries": costs,
        "gross_included_cost_roles": evidence.gross_included_cost_roles,
        "gross_cost_treatment_version": evidence.gross_cost_treatment_version,
        "gross_inclusion_manifest_hash": evidence.gross_inclusion_manifest_hash,
        "total_deductible_cost_bp": total_cost,
        "net_relative_value_bp": net,
        "missing_roles": missing_roles,
        "blockers": blockers,
        "research_only": True,
        "must_not_execute": True,
        "must_not_use_for_decision": True,
    }
    output_hash = canonical_hash(kwargs)
    return LiquidityPremiumAssessment(
        status=status,
        subject_id=evidence.subject_id,
        currency=evidence.currency,
        evaluated_at=evaluated_at,
        input_hash=input_hash,
        output_hash=output_hash,
        policy_hash=policy.policy_hash,
        market_spread_semantics=policy.market_spread_semantics,
        premium_rules=policy.premium_rules,
        cost_rules=policy.cost_rules,
        decomposition_tolerance_bp=policy.decomposition_tolerance_bp,
        allow_negative_model_premium=policy.allow_negative_model_premium,
        allow_negative_market_implied_premium=(policy.allow_negative_market_implied_premium),
        maximum_quote_age_seconds=policy.maximum_quote_age_seconds,
        minimum_turnover_ratio=policy.minimum_turnover_ratio,
        minimum_issue_size=policy.minimum_issue_size,
        quote_observed_at=next(
            (
                measure.observed_at
                for measure in evidence.measures
                if measure.role is LiquidityMeasureRole.BID_ASK_BP
            ),
            None,
        ),
        quote_age_seconds=quote_age_seconds,
        turnover_ratio=values.get(LiquidityMeasureRole.TURNOVER_RATIO),
        issue_size=values.get(LiquidityMeasureRole.ISSUE_SIZE),
        gross_relative_value_bp=gross,
        market_spread_bp=values.get(LiquidityMeasureRole.MARKET_SPREAD_BP),
        expected_credit_loss_bp=values.get(LiquidityMeasureRole.EXPECTED_CREDIT_LOSS_BP),
        option_cost_bp=values.get(LiquidityMeasureRole.OPTION_COST_BP),
        other_spread_bp=values.get(LiquidityMeasureRole.OTHER_SPREAD_BP),
        model_liquidity_premium_bp=model_premium,
        market_implied_liquidity_premium_bp=implied_premium,
        premium_components=components,
        cost_entries=costs,
        gross_included_cost_roles=evidence.gross_included_cost_roles,
        gross_cost_treatment_version=evidence.gross_cost_treatment_version,
        gross_inclusion_manifest_hash=evidence.gross_inclusion_manifest_hash,
        total_deductible_cost_bp=total_cost,
        net_relative_value_bp=net,
        missing_roles=missing_roles,
        blockers=blockers,
        research_only=True,
        must_not_execute=True,
        must_not_use_for_decision=True,
    )


from apps.fixed_income.domain.liquidity_premium_evaluation import (  # noqa: E402
    evaluate_liquidity_premium,
)

__all__ = [
    "LiquidityCostBasis",
    "LiquidityCostEntry",
    "LiquidityCostRule",
    "LiquidityMeasure",
    "LiquidityMeasureRole",
    "LiquidityPremiumAssessment",
    "LiquidityPremiumBlocker",
    "LiquidityPremiumBlockerCode",
    "LiquidityPremiumComponent",
    "LiquidityPremiumEvidence",
    "LiquidityPremiumPolicy",
    "LiquidityPremiumRule",
    "LiquidityPremiumStatus",
    "MarketSpreadSemantics",
    "evaluate_liquidity_premium",
    "liquidity_premium_input_hash",
]
