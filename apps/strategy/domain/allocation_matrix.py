"""Pure domain types and rules for versioned asset-allocation policies.

The allocation values themselves deliberately do not live in this module.  They
are mutable business configuration and are supplied by an activated Strategy
allocation-policy version through the application repository port.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256


class RegimeType(Enum):
    """Stable regime identifiers supported by allocation policies."""

    RECOVERY = "Recovery"
    OVERHEAT = "Overheat"
    STAGFLATION = "Stagflation"
    DEFLATION = "Deflation"


class RiskProfile(Enum):
    """Stable investor risk-profile identifiers."""

    AGGRESSIVE = "aggressive"
    MODERATE = "moderate"
    CONSERVATIVE = "conservative"
    DEFENSIVE = "defensive"


class PolicyLevel(Enum):
    """Stable policy-gear identifiers consumed by allocation policies."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class AllocationPolicyStatus(Enum):
    """Lifecycle state of an immutable allocation-policy version."""

    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class AllocationPolicySourceType(Enum):
    """Provenance classifications for allocation-policy versions."""

    LEGACY_CODE_MIGRATION = "legacy_code_migration"
    HUMAN = "human"
    APPROVED_RESEARCH = "approved_research"
    ROLLBACK = "rollback"


class AllocationStatisticsStatus(Enum):
    """Evidence status for expected return, volatility, and Sharpe values."""

    LEGACY_UNVERIFIED = "legacy_unverified"
    HUMAN_ASSUMPTION = "human_assumption"
    APPROVED_RESEARCH = "approved_research"
    NOT_PROVIDED = "not_provided"


class AllocationPolicyConfigurationError(ValueError):
    """Base error for missing, incomplete, or corrupt allocation policy data."""


class AllocationPolicyUnavailableError(AllocationPolicyConfigurationError):
    """Raised when no active allocation-policy version exists."""


class AllocationPolicyIntegrityError(AllocationPolicyConfigurationError):
    """Raised when stored policy data does not match its content hash."""


@dataclass(frozen=True)
class AssetAllocation:
    """Four-asset target weights expressed as fractions of one."""

    equity: float
    fixed_income: float
    commodity: float
    cash: float

    def __post_init__(self) -> None:
        """Reject non-finite, out-of-range, or non-normalized weights."""

        weights = (self.equity, self.fixed_income, self.commodity, self.cash)
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in weights):
            raise ValueError("asset allocation weights must be finite values between 0 and 1")
        total = sum(weights)
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError(f"allocation weights must sum to 1, got {total:.6f}")

    def to_percentage_dict(self) -> dict[str, float]:
        """Return weights as percentages for the established facade contract."""

        return {
            "equity": round(self.equity * 100, 1),
            "fixed_income": round(self.fixed_income * 100, 1),
            "commodity": round(self.commodity * 100, 1),
            "cash": round(self.cash * 100, 1),
        }


@dataclass(frozen=True)
class AllocationTarget:
    """One regime/risk target plus explicitly classified statistical assumptions."""

    allocation: AssetAllocation
    reasoning: str
    expected_return: float | None = None
    expected_volatility: float | None = None
    sharpe_ratio: float | None = None
    statistics_status: AllocationStatisticsStatus = AllocationStatisticsStatus.NOT_PROVIDED
    research_evidence_id: str | None = None
    allocation_policy_version: int | None = None
    allocation_policy_content_hash: str | None = None

    def __post_init__(self) -> None:
        """Validate optional statistics without upgrading their evidence status."""

        for field_name, value in (
            ("expected_return", self.expected_return),
            ("expected_volatility", self.expected_volatility),
            ("sharpe_ratio", self.sharpe_ratio),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{field_name} must be finite when provided")
        if self.expected_volatility is not None and self.expected_volatility < 0:
            raise ValueError("expected_volatility cannot be negative")
        if (
            self.statistics_status is AllocationStatisticsStatus.APPROVED_RESEARCH
            and not self.research_evidence_id
        ):
            raise ValueError("approved research statistics require research_evidence_id")

    @property
    def must_not_use_statistics_as_model_estimate(self) -> bool:
        """Return whether the statistics lack approved research evidence."""

        return self.statistics_status is not AllocationStatisticsStatus.APPROVED_RESEARCH


@dataclass(frozen=True)
class AllocationPolicyEntry:
    """One matrix cell in a versioned allocation policy."""

    regime: RegimeType
    risk_profile: RiskProfile
    target: AllocationTarget


@dataclass(frozen=True)
class PolicyAllocationAdjustment:
    """Policy-gear multipliers owned by the same allocation-policy version."""

    policy_level: PolicyLevel
    equity_multiplier: float
    expected_return_multiplier: float = 1.0
    expected_volatility_multiplier: float = 1.0
    sharpe_multiplier: float = 1.0

    def __post_init__(self) -> None:
        """Validate multipliers at the domain boundary."""

        multipliers = (
            self.equity_multiplier,
            self.expected_return_multiplier,
            self.expected_volatility_multiplier,
            self.sharpe_multiplier,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in multipliers):
            raise ValueError("allocation policy multipliers must be finite and non-negative")
        if self.equity_multiplier > 1.0:
            raise ValueError("equity_multiplier cannot exceed 1")


@dataclass(frozen=True)
class AllocationPolicyDraft:
    """Immutable input used to create the next policy version."""

    policy_key: str
    entries: tuple[AllocationPolicyEntry, ...]
    adjustments: tuple[PolicyAllocationAdjustment, ...]
    source_type: AllocationPolicySourceType
    change_reason: str
    based_on_version: int | None = None
    created_by_id: int | None = None

    def __post_init__(self) -> None:
        """Validate policy identity and duplicate matrix keys."""

        if not self.policy_key.strip():
            raise ValueError("policy_key is required")
        if not self.change_reason.strip():
            raise ValueError("change_reason is required")
        _validate_unique_policy_keys(self.entries, self.adjustments)

    def validate_for_activation(self) -> None:
        """Require a complete 4x4 matrix and all policy-gear adjustments."""

        expected_cells = {(regime, risk) for regime in RegimeType for risk in RiskProfile}
        actual_cells = {(entry.regime, entry.risk_profile) for entry in self.entries}
        if actual_cells != expected_cells:
            missing = sorted(
                f"{regime.value}/{risk.value}" for regime, risk in expected_cells - actual_cells
            )
            extra = sorted(
                f"{regime.value}/{risk.value}" for regime, risk in actual_cells - expected_cells
            )
            raise AllocationPolicyConfigurationError(
                f"allocation policy matrix is incomplete; missing={missing}, extra={extra}"
            )

        expected_levels = set(PolicyLevel)
        actual_levels = {adjustment.policy_level for adjustment in self.adjustments}
        if actual_levels != expected_levels:
            missing_levels = sorted(level.value for level in expected_levels - actual_levels)
            raise AllocationPolicyConfigurationError(
                f"allocation policy adjustments are incomplete; missing={missing_levels}"
            )


@dataclass(frozen=True)
class AllocationPolicyVersion:
    """Stored immutable allocation-policy content plus lifecycle metadata."""

    policy_key: str
    version: int
    status: AllocationPolicyStatus
    entries: tuple[AllocationPolicyEntry, ...]
    adjustments: tuple[PolicyAllocationAdjustment, ...]
    content_hash: str
    source_type: AllocationPolicySourceType
    change_reason: str
    created_at: datetime
    effective_at: datetime | None = None
    based_on_version: int | None = None
    created_by_id: int | None = None

    def __post_init__(self) -> None:
        """Validate identifiers, aware timestamps, uniqueness, and the content hash."""

        if not self.policy_key.strip():
            raise ValueError("policy_key is required")
        if self.version <= 0:
            raise ValueError("allocation policy version must be positive")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if self.effective_at is not None and (
            self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None
        ):
            raise ValueError("effective_at must be timezone-aware")
        _validate_unique_policy_keys(self.entries, self.adjustments)
        calculated_hash = calculate_allocation_policy_content_hash(
            self.entries,
            self.adjustments,
        )
        if calculated_hash != self.content_hash:
            raise AllocationPolicyIntegrityError(
                "allocation policy content hash does not match stored policy content"
            )

    def as_draft(
        self,
        *,
        source_type: AllocationPolicySourceType,
        change_reason: str,
        created_by_id: int | None,
    ) -> AllocationPolicyDraft:
        """Copy this version's content into a new immutable draft."""

        return AllocationPolicyDraft(
            policy_key=self.policy_key,
            entries=self.entries,
            adjustments=self.adjustments,
            source_type=source_type,
            change_reason=change_reason,
            based_on_version=self.version,
            created_by_id=created_by_id,
        )

    def validate_for_activation(self) -> None:
        """Validate that this stored version is complete enough to activate."""

        AllocationPolicyDraft(
            policy_key=self.policy_key,
            entries=self.entries,
            adjustments=self.adjustments,
            source_type=self.source_type,
            change_reason=self.change_reason,
            based_on_version=self.based_on_version,
            created_by_id=self.created_by_id,
        ).validate_for_activation()


def calculate_allocation_policy_content_hash(
    entries: tuple[AllocationPolicyEntry, ...],
    adjustments: tuple[PolicyAllocationAdjustment, ...],
) -> str:
    """Return a deterministic SHA-256 hash for policy content."""

    entry_payload = []
    for entry in sorted(entries, key=lambda item: (item.regime.value, item.risk_profile.value)):
        target = entry.target
        entry_payload.append(
            {
                "regime": entry.regime.value,
                "risk_profile": entry.risk_profile.value,
                "allocation": {
                    "equity": _canonical_number(target.allocation.equity, decimal_places=6),
                    "fixed_income": _canonical_number(
                        target.allocation.fixed_income, decimal_places=6
                    ),
                    "commodity": _canonical_number(target.allocation.commodity, decimal_places=6),
                    "cash": _canonical_number(target.allocation.cash, decimal_places=6),
                },
                "reasoning": target.reasoning,
                "expected_return": _canonical_optional_number(
                    target.expected_return, decimal_places=8
                ),
                "expected_volatility": _canonical_optional_number(
                    target.expected_volatility, decimal_places=8
                ),
                "sharpe_ratio": _canonical_optional_number(target.sharpe_ratio, decimal_places=8),
                "statistics_status": target.statistics_status.value,
                "research_evidence_id": target.research_evidence_id,
            }
        )

    adjustment_payload = []
    for adjustment in sorted(adjustments, key=lambda item: item.policy_level.value):
        adjustment_payload.append(
            {
                "policy_level": adjustment.policy_level.value,
                "equity_multiplier": _canonical_number(
                    adjustment.equity_multiplier, decimal_places=6
                ),
                "expected_return_multiplier": _canonical_number(
                    adjustment.expected_return_multiplier, decimal_places=6
                ),
                "expected_volatility_multiplier": _canonical_number(
                    adjustment.expected_volatility_multiplier, decimal_places=6
                ),
                "sharpe_multiplier": _canonical_number(
                    adjustment.sharpe_multiplier, decimal_places=6
                ),
            }
        )

    canonical_json = json.dumps(
        {"entries": entry_payload, "adjustments": adjustment_payload},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()


def resolve_allocation_target(
    policy: AllocationPolicyVersion,
    regime: str,
    risk_profile: str,
    policy_level: str | None = None,
) -> AllocationTarget:
    """Resolve and adjust a target exclusively from one activated policy version."""

    if policy.status is not AllocationPolicyStatus.ACTIVE:
        raise AllocationPolicyConfigurationError(
            f"allocation policy {policy.policy_key} v{policy.version} is not active"
        )
    policy.validate_for_activation()

    try:
        regime_enum = RegimeType(regime)
    except ValueError:
        raise ValueError(f"invalid regime: {regime}") from None
    try:
        risk_enum = RiskProfile(risk_profile)
    except ValueError:
        raise ValueError(f"invalid risk profile: {risk_profile}") from None
    try:
        policy_enum = PolicyLevel(policy_level or PolicyLevel.P0.value)
    except ValueError:
        raise ValueError(f"invalid policy level: {policy_level}") from None

    entry = next(
        (
            item
            for item in policy.entries
            if item.regime is regime_enum and item.risk_profile is risk_enum
        ),
        None,
    )
    adjustment = next(
        (item for item in policy.adjustments if item.policy_level is policy_enum),
        None,
    )
    if entry is None or adjustment is None:
        raise AllocationPolicyConfigurationError(
            "active allocation policy is missing the requested matrix cell or policy adjustment"
        )

    target = entry.target
    original_equity = target.allocation.equity
    adjusted_equity = original_equity * adjustment.equity_multiplier
    equity_reduction = original_equity - adjusted_equity
    other_total = target.allocation.fixed_income + target.allocation.cash
    if other_total > 0:
        fixed_income_add = equity_reduction * (target.allocation.fixed_income / other_total)
        cash_add = equity_reduction * (target.allocation.cash / other_total)
    else:
        fixed_income_add = equity_reduction / 2.0
        cash_add = equity_reduction / 2.0

    adjusted_allocation = AssetAllocation(
        equity=adjusted_equity,
        fixed_income=target.allocation.fixed_income + fixed_income_add,
        commodity=target.allocation.commodity,
        cash=target.allocation.cash + cash_add,
    )
    reasoning = target.reasoning
    if adjustment.equity_multiplier < 1.0:
        reasoning = (
            f"{reasoning}。\u3010{policy_enum.value}政策收紧\u3011权益仓位已从"
            f"{original_equity * 100:.0f}%降至{adjusted_equity * 100:.0f}%"
        )

    return replace(
        target,
        allocation=adjusted_allocation,
        reasoning=reasoning,
        expected_return=_multiply_optional(
            target.expected_return,
            adjustment.expected_return_multiplier,
        ),
        expected_volatility=_multiply_optional(
            target.expected_volatility,
            adjustment.expected_volatility_multiplier,
        ),
        sharpe_ratio=_multiply_optional(target.sharpe_ratio, adjustment.sharpe_multiplier),
        allocation_policy_version=policy.version,
        allocation_policy_content_hash=policy.content_hash,
    )


def _validate_unique_policy_keys(
    entries: tuple[AllocationPolicyEntry, ...],
    adjustments: tuple[PolicyAllocationAdjustment, ...],
) -> None:
    """Reject duplicate matrix cells and policy-level adjustments."""

    entry_keys = [(entry.regime, entry.risk_profile) for entry in entries]
    if len(entry_keys) != len(set(entry_keys)):
        raise ValueError("allocation policy contains duplicate regime/risk cells")
    adjustment_keys = [adjustment.policy_level for adjustment in adjustments]
    if len(adjustment_keys) != len(set(adjustment_keys)):
        raise ValueError("allocation policy contains duplicate policy adjustments")


def _canonical_number(value: float, *, decimal_places: int) -> str:
    """Normalize a finite numeric value for cross-database hashing."""

    if not math.isfinite(value):
        raise ValueError("allocation policy content cannot contain non-finite values")
    quantizer = Decimal(1).scaleb(-decimal_places)
    normalized = Decimal(str(value)).quantize(quantizer).normalize()
    return format(normalized, "f")


def _canonical_optional_number(
    value: float | None,
    *,
    decimal_places: int,
) -> str | None:
    """Normalize an optional finite numeric value for hashing."""

    return None if value is None else _canonical_number(value, decimal_places=decimal_places)


def _multiply_optional(value: float | None, multiplier: float) -> float | None:
    """Scale an optional statistic while preserving a real zero value."""

    return None if value is None else value * multiplier
