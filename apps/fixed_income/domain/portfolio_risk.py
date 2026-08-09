"""Pure R5 fixed-income portfolio risk budgets and stress calculations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, StrEnum

_BASIS_POINT = Decimal("0.0001")


def _require_text(value: str, field_name: str, *, maximum: int = 200) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be a bounded non-blank string")


def _require_token(value: str, field_name: str, *, maximum: int = 160) -> None:
    _require_text(value, field_name, maximum=maximum)
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a SHA-256 digest")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _canonical_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if is_dataclass(value):
        return {field.name: _canonical_value(getattr(value, field.name)) for field in fields(value)}
    return value


def _sha256_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _canonical_value(payload),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class PublicationRole(StrEnum):
    """Required canonical evidence roles for every portfolio position."""

    POSITION_VALUATION = "position_valuation"
    INTEREST_RATE_ANALYTICS = "interest_rate_analytics"
    CREDIT_ANALYTICS = "credit_analytics"
    LIQUIDITY_ANALYTICS = "liquidity_analytics"


_PUBLICATION_ROLE_OWNER: dict[PublicationRole, str] = {
    PublicationRole.POSITION_VALUATION: "data_center",
    PublicationRole.INTEREST_RATE_ANALYTICS: "fixed_income",
    PublicationRole.CREDIT_ANALYTICS: "fixed_income",
    PublicationRole.LIQUIDITY_ANALYTICS: "data_center",
}


class RateShockKind(StrEnum):
    """Shape label for a fully injected key-rate shock vector."""

    PARALLEL = "parallel"
    KEY_RATE = "key_rate"
    STEEPENER = "steepener"
    FLATTENING = "flattening"


class PortfolioRiskStatus(StrEnum):
    """Fail-closed status of one research portfolio assessment."""

    AVAILABLE = "available"
    BLOCKED = "blocked"


class PortfolioRiskBlockerCode(StrEnum):
    """Stable R5 portfolio-risk failure and budget reason codes."""

    CANONICAL_BUNDLE_MISSING = "fixed_income.portfolio_risk.bundle.missing"
    BUDGET_POLICY_MISSING = "fixed_income.portfolio_risk.policy.missing"
    INPUT_HASH_MISMATCH = "fixed_income.portfolio_risk.input.hash_mismatch"
    PORTFOLIO_SNAPSHOT_MISMATCH = "fixed_income.portfolio_risk.snapshot.mismatch"
    BUNDLE_POLICY_MISMATCH = "fixed_income.portfolio_risk.bundle.policy_mismatch"
    POLICY_HASH_MISMATCH = "fixed_income.portfolio_risk.policy.hash_mismatch"
    BUNDLE_STALE = "fixed_income.portfolio_risk.bundle.stale"
    POLICY_INACTIVE = "fixed_income.portfolio_risk.policy.inactive"
    EVIDENCE_FROM_FUTURE = "fixed_income.portfolio_risk.evidence.from_future"
    AS_OF_MISMATCH = "fixed_income.portfolio_risk.as_of.mismatch"
    CURRENCY_MISMATCH = "fixed_income.portfolio_risk.currency.mismatch"
    PIT_MANIFEST_HASH_MISMATCH = "fixed_income.portfolio_risk.pit.hash_mismatch"
    PIT_MANIFEST_INCOMPLETE = "fixed_income.portfolio_risk.pit.incomplete"
    PIT_MANIFEST_STALE = "fixed_income.portfolio_risk.pit.stale"
    PUBLICATION_IDENTITY_MISMATCH = "fixed_income.portfolio_risk.publication.identity_mismatch"
    PUBLICATION_FROM_FUTURE = "fixed_income.portfolio_risk.publication.from_future"
    PUBLICATION_STALE = "fixed_income.portfolio_risk.publication.stale"
    RATE_SHOCK_UNIVERSE_MISMATCH = "fixed_income.portfolio_risk.shock.rate_universe_mismatch"
    CREDIT_SHOCK_UNIVERSE_MISMATCH = "fixed_income.portfolio_risk.shock.credit_universe_mismatch"
    KEY_RATE_DURATION_IDENTITY_FAILED = "fixed_income.portfolio_risk.identity.key_rate_duration"
    KEY_RATE_CONVEXITY_IDENTITY_FAILED = "fixed_income.portfolio_risk.identity.key_rate_convexity"
    CONTRIBUTION_IDENTITY_FAILED = "fixed_income.portfolio_risk.identity.contribution"
    DV01_BUDGET_BREACHED = "fixed_income.portfolio_risk.budget.dv01"
    CS01_BUDGET_BREACHED = "fixed_income.portfolio_risk.budget.cs01"
    CONVEXITY_BUDGET_BREACHED = "fixed_income.portfolio_risk.budget.convexity"
    LIQUIDITY_FRACTION_BREACHED = "fixed_income.portfolio_risk.budget.liquidatable_fraction"
    LIQUIDITY_COST_BREACHED = "fixed_income.portfolio_risk.budget.liquidity_cost"
    STRESS_LOSS_BUDGET_BREACHED = "fixed_income.portfolio_risk.budget.stress_loss"


@dataclass(frozen=True)
class PortfolioRiskPublicationReference:
    """One Data Center publication used by one exact position input."""

    role: PublicationRole
    owner: str
    subject_id: str
    currency: str
    dataset_key: str
    publication_id: str
    content_hash: str
    observed_at: datetime
    published_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.role, PublicationRole):
            raise ValueError("publication role is invalid")
        for name in (
            "owner",
            "subject_id",
            "currency",
            "dataset_key",
            "publication_id",
        ):
            _require_token(str(getattr(self, name)), f"PortfolioRiskPublicationReference.{name}")
        expected_owner = _PUBLICATION_ROLE_OWNER[self.role]
        if self.owner != expected_owner:
            raise ValueError(f"{self.role.value} evidence must be owned by {expected_owner}")
        _require_sha256(self.content_hash, "PortfolioRiskPublicationReference.content_hash")
        for name in ("observed_at", "published_at", "valid_until"):
            _require_aware(getattr(self, name), f"PortfolioRiskPublicationReference.{name}")
        if self.published_at < self.observed_at:
            raise ValueError("publication published_at cannot precede observed_at")
        if self.valid_until <= self.published_at:
            raise ValueError("publication valid_until must follow published_at")

    @property
    def identity(self) -> tuple[str, str, str]:
        """Return the exact dataset/publication/content identity."""

        return (self.dataset_key, self.publication_id, self.content_hash.lower())


@dataclass(frozen=True)
class PITPublicationIdentity:
    """Publication identity included in the canonical PIT manifest."""

    dataset_key: str
    publication_id: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.dataset_key, "PITPublicationIdentity.dataset_key")
        _require_token(self.publication_id, "PITPublicationIdentity.publication_id")
        _require_sha256(self.content_hash, "PITPublicationIdentity.content_hash")

    @property
    def identity(self) -> tuple[str, str, str]:
        """Return the normalized exact identity."""

        return (self.dataset_key, self.publication_id, self.content_hash.lower())


@dataclass(frozen=True)
class PortfolioRiskPITManifest:
    """Complete PIT publication manifest for one portfolio risk bundle."""

    manifest_id: str
    manifest_hash: str
    as_of: datetime
    observed_at: datetime
    valid_until: datetime
    coverage_ratio: Decimal
    missing_count: int
    estimated_count: int
    unknown_count: int
    publication_identities: tuple[PITPublicationIdentity, ...]

    def __post_init__(self) -> None:
        _require_token(self.manifest_id, "PortfolioRiskPITManifest.manifest_id")
        _require_sha256(self.manifest_hash, "PortfolioRiskPITManifest.manifest_hash")
        for name in ("as_of", "observed_at", "valid_until"):
            _require_aware(getattr(self, name), f"PortfolioRiskPITManifest.{name}")
        if self.valid_until <= self.observed_at:
            raise ValueError("PIT manifest valid_until must follow observed_at")
        _require_finite(self.coverage_ratio, "PortfolioRiskPITManifest.coverage_ratio")
        if not Decimal("0") <= self.coverage_ratio <= Decimal("1"):
            raise ValueError("PIT manifest coverage_ratio must be between zero and one")
        for name in ("missing_count", "estimated_count", "unknown_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"PortfolioRiskPITManifest.{name} cannot be negative")
        identities = tuple(item.identity for item in self.publication_identities)
        if not identities or len(identities) != len(set(identities)):
            raise ValueError("PIT publication identities must be non-empty and unique")

    @property
    def calculated_manifest_hash(self) -> str:
        """Return the canonical manifest digest."""

        return build_pit_manifest_hash(
            manifest_id=self.manifest_id,
            as_of=self.as_of,
            observed_at=self.observed_at,
            valid_until=self.valid_until,
            coverage_ratio=self.coverage_ratio,
            missing_count=self.missing_count,
            estimated_count=self.estimated_count,
            unknown_count=self.unknown_count,
            publication_identities=self.publication_identities,
        )


def build_pit_manifest_hash(
    *,
    manifest_id: str,
    as_of: datetime,
    observed_at: datetime,
    valid_until: datetime,
    coverage_ratio: Decimal,
    missing_count: int,
    estimated_count: int,
    unknown_count: int,
    publication_identities: tuple[PITPublicationIdentity, ...],
) -> str:
    """Build the canonical SHA-256 for a portfolio risk PIT manifest."""

    payload = {
        "manifest_id": manifest_id,
        "as_of": as_of,
        "observed_at": observed_at,
        "valid_until": valid_until,
        "coverage_ratio": coverage_ratio,
        "missing_count": missing_count,
        "estimated_count": estimated_count,
        "unknown_count": unknown_count,
        "publication_identities": tuple(
            sorted(publication_identities, key=lambda item: item.identity)
        ),
    }
    return _sha256_payload(payload)


@dataclass(frozen=True)
class KeyRateExposure:
    """Position duration and diagonal convexity exposure at one key tenor."""

    tenor_years: Decimal
    duration_years: Decimal
    convexity_years_squared: Decimal

    def __post_init__(self) -> None:
        for name in ("tenor_years", "duration_years", "convexity_years_squared"):
            _require_finite(getattr(self, name), f"KeyRateExposure.{name}")
        if self.tenor_years <= 0:
            raise ValueError("key-rate tenor must be positive")
        if self.duration_years < 0 or self.convexity_years_squared < 0:
            raise ValueError("key-rate duration and convexity cannot be negative")


@dataclass(frozen=True)
class FixedIncomePositionRiskInput:
    """Canonical per-position sensitivities and liquidity observations."""

    position_id: str
    instrument_id: str
    currency: str
    as_of: datetime
    market_value: Decimal
    modified_duration_years: Decimal
    convexity_years_squared: Decimal
    credit_bucket: str
    credit_spread_duration_years: Decimal
    liquidatable_fraction: Decimal
    liquidity_cost_rate: Decimal
    key_rate_exposures: tuple[KeyRateExposure, ...]
    publication_references: tuple[PortfolioRiskPublicationReference, ...]

    def __post_init__(self) -> None:
        for name in ("position_id", "instrument_id", "currency", "credit_bucket"):
            _require_token(str(getattr(self, name)), f"FixedIncomePositionRiskInput.{name}")
        _require_aware(self.as_of, "FixedIncomePositionRiskInput.as_of")
        for name in (
            "market_value",
            "modified_duration_years",
            "convexity_years_squared",
            "credit_spread_duration_years",
            "liquidatable_fraction",
            "liquidity_cost_rate",
        ):
            _require_finite(getattr(self, name), f"FixedIncomePositionRiskInput.{name}")
        if self.market_value <= 0:
            raise ValueError("position market_value must be positive")
        if (
            self.modified_duration_years < 0
            or self.convexity_years_squared < 0
            or self.credit_spread_duration_years < 0
        ):
            raise ValueError("position risk sensitivities cannot be negative")
        if not Decimal("0") <= self.liquidatable_fraction <= Decimal("1"):
            raise ValueError("position liquidatable_fraction must be between zero and one")
        if self.liquidity_cost_rate < 0:
            raise ValueError("position liquidity_cost_rate cannot be negative")
        tenors = tuple(item.tenor_years for item in self.key_rate_exposures)
        if not tenors or tenors != tuple(sorted(tenors)) or len(tenors) != len(set(tenors)):
            raise ValueError("position key-rate tenors must be non-empty, ascending, and unique")
        roles = tuple(reference.role for reference in self.publication_references)
        if set(roles) != set(PublicationRole) or len(roles) != len(set(roles)):
            raise ValueError("position publication roles must exactly cover every required role")


@dataclass(frozen=True)
class RateShockPoint:
    """Explicit yield shock in basis points at one key tenor."""

    tenor_years: Decimal
    shock_bp: Decimal

    def __post_init__(self) -> None:
        _require_finite(self.tenor_years, "RateShockPoint.tenor_years")
        _require_finite(self.shock_bp, "RateShockPoint.shock_bp")
        if self.tenor_years <= 0:
            raise ValueError("rate shock tenor must be positive")


@dataclass(frozen=True)
class CreditSpreadShock:
    """Explicit credit-spread shock in basis points for one governed bucket."""

    credit_bucket: str
    shock_bp: Decimal

    def __post_init__(self) -> None:
        _require_token(self.credit_bucket, "CreditSpreadShock.credit_bucket")
        _require_finite(self.shock_bp, "CreditSpreadShock.shock_bp")


@dataclass(frozen=True)
class PortfolioStressScenario:
    """Versioned rate-shape and credit shock with no implicit default node."""

    scenario_id: str
    scenario_version: str
    rate_shock_kind: RateShockKind
    rate_shocks: tuple[RateShockPoint, ...]
    credit_shocks: tuple[CreditSpreadShock, ...]

    def __post_init__(self) -> None:
        _require_token(self.scenario_id, "PortfolioStressScenario.scenario_id")
        _require_token(self.scenario_version, "PortfolioStressScenario.scenario_version")
        if not isinstance(self.rate_shock_kind, RateShockKind):
            raise ValueError("rate shock kind is invalid")
        tenors = tuple(item.tenor_years for item in self.rate_shocks)
        if not tenors or tenors != tuple(sorted(tenors)) or len(tenors) != len(set(tenors)):
            raise ValueError("scenario rate shocks must be non-empty, ascending, and unique")
        buckets = tuple(item.credit_bucket for item in self.credit_shocks)
        if len(buckets) != len(set(buckets)):
            raise ValueError("scenario credit shock buckets must be unique")
        shock_values = tuple(item.shock_bp for item in self.rate_shocks)
        if self.rate_shock_kind is RateShockKind.PARALLEL and len(set(shock_values)) != 1:
            raise ValueError("parallel rate shock requires one equal shock at every tenor")
        if self.rate_shock_kind is RateShockKind.STEEPENER and any(
            left >= right for left, right in zip(shock_values, shock_values[1:], strict=False)
        ):
            raise ValueError("steepener shocks must increase with tenor")
        if self.rate_shock_kind is RateShockKind.FLATTENING and any(
            left <= right for left, right in zip(shock_values, shock_values[1:], strict=False)
        ):
            raise ValueError("flattening shocks must decrease with tenor")


@dataclass(frozen=True)
class FixedIncomeRiskBudgetPolicy:
    """Versioned, injected portfolio risk and stress budgets."""

    policy_version: str
    currency: str
    activated_at: datetime
    valid_until: datetime
    maximum_absolute_dv01: Decimal
    maximum_absolute_cs01: Decimal
    maximum_convexity_exposure: Decimal
    minimum_liquidatable_fraction: Decimal
    maximum_liquidity_cost: Decimal
    maximum_stress_loss: Decimal
    identity_tolerance: Decimal
    policy_hash: str

    def __post_init__(self) -> None:
        _require_token(self.policy_version, "FixedIncomeRiskBudgetPolicy.policy_version")
        _require_token(self.currency, "FixedIncomeRiskBudgetPolicy.currency")
        _require_aware(self.activated_at, "FixedIncomeRiskBudgetPolicy.activated_at")
        _require_aware(self.valid_until, "FixedIncomeRiskBudgetPolicy.valid_until")
        if self.valid_until <= self.activated_at:
            raise ValueError("risk budget policy valid_until must follow activated_at")
        for name in (
            "maximum_absolute_dv01",
            "maximum_absolute_cs01",
            "maximum_convexity_exposure",
            "minimum_liquidatable_fraction",
            "maximum_liquidity_cost",
            "maximum_stress_loss",
            "identity_tolerance",
        ):
            value = getattr(self, name)
            _require_finite(value, f"FixedIncomeRiskBudgetPolicy.{name}")
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.minimum_liquidatable_fraction > 1:
            raise ValueError("minimum_liquidatable_fraction cannot exceed one")
        _require_sha256(self.policy_hash, "FixedIncomeRiskBudgetPolicy.policy_hash")
        if self.policy_hash.lower() != self.calculated_policy_hash:
            raise ValueError("fixed-income risk budget policy_hash mismatch")

    @property
    def calculated_policy_hash(self) -> str:
        """Return the canonical digest over every budget and clock."""

        return build_fixed_income_risk_budget_policy_hash(
            policy_version=self.policy_version,
            currency=self.currency,
            activated_at=self.activated_at,
            valid_until=self.valid_until,
            maximum_absolute_dv01=self.maximum_absolute_dv01,
            maximum_absolute_cs01=self.maximum_absolute_cs01,
            maximum_convexity_exposure=self.maximum_convexity_exposure,
            minimum_liquidatable_fraction=self.minimum_liquidatable_fraction,
            maximum_liquidity_cost=self.maximum_liquidity_cost,
            maximum_stress_loss=self.maximum_stress_loss,
            identity_tolerance=self.identity_tolerance,
        )


def build_fixed_income_risk_budget_policy_hash(
    *,
    policy_version: str,
    currency: str,
    activated_at: datetime,
    valid_until: datetime,
    maximum_absolute_dv01: Decimal,
    maximum_absolute_cs01: Decimal,
    maximum_convexity_exposure: Decimal,
    minimum_liquidatable_fraction: Decimal,
    maximum_liquidity_cost: Decimal,
    maximum_stress_loss: Decimal,
    identity_tolerance: Decimal,
) -> str:
    """Build the canonical SHA-256 over a complete risk budget policy."""

    return _sha256_payload(
        {
            "policy_version": policy_version,
            "currency": currency,
            "activated_at": activated_at,
            "valid_until": valid_until,
            "maximum_absolute_dv01": maximum_absolute_dv01,
            "maximum_absolute_cs01": maximum_absolute_cs01,
            "maximum_convexity_exposure": maximum_convexity_exposure,
            "minimum_liquidatable_fraction": minimum_liquidatable_fraction,
            "maximum_liquidity_cost": maximum_liquidity_cost,
            "maximum_stress_loss": maximum_stress_loss,
            "identity_tolerance": identity_tolerance,
        }
    )


@dataclass(frozen=True)
class PortfolioRiskInputBundle:
    """Canonical, PIT-bound input bundle for one portfolio risk assessment."""

    bundle_id: str
    bundle_version: str
    portfolio_snapshot_id: str
    portfolio_snapshot_owner: str
    portfolio_snapshot_hash: str
    portfolio_snapshot_as_of: datetime
    budget_policy_version: str
    budget_policy_hash: str
    currency: str
    as_of: datetime
    created_at: datetime
    valid_until: datetime
    pit_manifest: PortfolioRiskPITManifest
    positions: tuple[FixedIncomePositionRiskInput, ...]
    stress_scenarios: tuple[PortfolioStressScenario, ...]
    input_hash: str

    def __post_init__(self) -> None:
        for name in (
            "bundle_id",
            "bundle_version",
            "portfolio_snapshot_id",
            "portfolio_snapshot_owner",
            "budget_policy_version",
            "currency",
        ):
            _require_token(str(getattr(self, name)), f"PortfolioRiskInputBundle.{name}")
        if self.portfolio_snapshot_owner != "portfolio":
            raise ValueError("canonical portfolio snapshot must be owned by portfolio")
        _require_sha256(
            self.portfolio_snapshot_hash,
            "PortfolioRiskInputBundle.portfolio_snapshot_hash",
        )
        _require_sha256(self.budget_policy_hash, "PortfolioRiskInputBundle.budget_policy_hash")
        for name in ("portfolio_snapshot_as_of", "as_of", "created_at", "valid_until"):
            _require_aware(getattr(self, name), f"PortfolioRiskInputBundle.{name}")
        if self.created_at < self.as_of:
            raise ValueError("risk bundle created_at cannot precede as_of")
        if self.valid_until <= self.created_at:
            raise ValueError("risk bundle valid_until must follow created_at")
        position_ids = tuple(item.position_id for item in self.positions)
        if not position_ids or len(position_ids) != len(set(position_ids)):
            raise ValueError("risk bundle position identities must be non-empty and unique")
        scenario_ids = tuple(item.scenario_id for item in self.stress_scenarios)
        if not scenario_ids or len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("risk bundle stress scenario identities must be non-empty and unique")
        _require_sha256(self.input_hash, "PortfolioRiskInputBundle.input_hash")

    @property
    def calculated_input_hash(self) -> str:
        """Return the canonical input digest."""

        return build_portfolio_risk_input_hash(
            bundle_id=self.bundle_id,
            bundle_version=self.bundle_version,
            portfolio_snapshot_id=self.portfolio_snapshot_id,
            portfolio_snapshot_owner=self.portfolio_snapshot_owner,
            portfolio_snapshot_hash=self.portfolio_snapshot_hash,
            portfolio_snapshot_as_of=self.portfolio_snapshot_as_of,
            budget_policy_version=self.budget_policy_version,
            budget_policy_hash=self.budget_policy_hash,
            currency=self.currency,
            as_of=self.as_of,
            created_at=self.created_at,
            valid_until=self.valid_until,
            pit_manifest=self.pit_manifest,
            positions=self.positions,
            stress_scenarios=self.stress_scenarios,
        )


def build_portfolio_risk_input_hash(
    *,
    bundle_id: str,
    bundle_version: str,
    portfolio_snapshot_id: str,
    portfolio_snapshot_owner: str,
    portfolio_snapshot_hash: str,
    portfolio_snapshot_as_of: datetime,
    budget_policy_version: str,
    budget_policy_hash: str,
    currency: str,
    as_of: datetime,
    created_at: datetime,
    valid_until: datetime,
    pit_manifest: PortfolioRiskPITManifest,
    positions: tuple[FixedIncomePositionRiskInput, ...],
    stress_scenarios: tuple[PortfolioStressScenario, ...],
) -> str:
    """Build the canonical SHA-256 over every portfolio risk input."""

    payload = {
        "bundle_id": bundle_id,
        "bundle_version": bundle_version,
        "portfolio_snapshot_id": portfolio_snapshot_id,
        "portfolio_snapshot_owner": portfolio_snapshot_owner,
        "portfolio_snapshot_hash": portfolio_snapshot_hash,
        "portfolio_snapshot_as_of": portfolio_snapshot_as_of,
        "budget_policy_version": budget_policy_version,
        "budget_policy_hash": budget_policy_hash,
        "currency": currency,
        "as_of": as_of,
        "created_at": created_at,
        "valid_until": valid_until,
        "pit_manifest": pit_manifest,
        "positions": tuple(sorted(positions, key=lambda item: item.position_id)),
        "stress_scenarios": tuple(sorted(stress_scenarios, key=lambda item: item.scenario_id)),
    }
    return _sha256_payload(payload)


@dataclass(frozen=True)
class PortfolioRiskBlocker:
    """One stable blocker with optional position or scenario scope."""

    code: PortfolioRiskBlockerCode
    detail: str
    position_id: str | None = None
    scenario_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, PortfolioRiskBlockerCode):
            raise ValueError("portfolio risk blocker code is invalid")
        _require_text(self.detail, "PortfolioRiskBlocker.detail", maximum=500)


@dataclass(frozen=True)
class PositionRiskContribution:
    """Per-position contribution to portfolio sensitivities and liquidity."""

    position_id: str
    market_value: Decimal
    dv01: Decimal
    cs01: Decimal
    convexity_exposure: Decimal
    liquidatable_value: Decimal
    liquidity_cost: Decimal


@dataclass(frozen=True)
class PortfolioRiskTotals:
    """Portfolio sensitivity and liquidity totals."""

    market_value: Decimal
    dv01: Decimal
    cs01: Decimal
    convexity_exposure: Decimal
    liquidatable_value: Decimal
    liquidatable_fraction: Decimal
    liquidity_cost: Decimal


@dataclass(frozen=True)
class PositionStressContribution:
    """Per-position first-order, convexity, credit, and total stress P&L."""

    position_id: str
    rate_first_order_pnl: Decimal
    rate_convexity_pnl: Decimal
    credit_pnl: Decimal
    total_pnl: Decimal


@dataclass(frozen=True)
class StressScenarioResult:
    """Portfolio stress result with an explicit contribution identity."""

    scenario_id: str
    scenario_version: str
    rate_shock_kind: RateShockKind
    rate_first_order_pnl: Decimal
    rate_convexity_pnl: Decimal
    credit_pnl: Decimal
    total_pnl: Decimal
    loss: Decimal
    position_contributions: tuple[PositionStressContribution, ...]


@dataclass(frozen=True)
class FixedIncomePortfolioRiskAssessment:
    """Canonical research-only R5 portfolio risk and stress evidence."""

    status: PortfolioRiskStatus
    bundle_id: str
    portfolio_snapshot_id: str | None
    portfolio_snapshot_hash: str | None
    policy_version: str
    policy_hash: str | None
    evaluated_at: datetime
    input_hash: str | None
    totals: PortfolioRiskTotals | None
    position_contributions: tuple[PositionRiskContribution, ...]
    stress_results: tuple[StressScenarioResult, ...]
    blockers: tuple[PortfolioRiskBlocker, ...]
    output_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.status, PortfolioRiskStatus):
            raise ValueError("portfolio risk assessment status is invalid")
        _require_token(self.bundle_id, "FixedIncomePortfolioRiskAssessment.bundle_id")
        _require_token(self.policy_version, "FixedIncomePortfolioRiskAssessment.policy_version")
        if self.portfolio_snapshot_id is not None:
            _require_token(
                self.portfolio_snapshot_id,
                "FixedIncomePortfolioRiskAssessment.portfolio_snapshot_id",
            )
        if self.portfolio_snapshot_hash is not None:
            _require_sha256(
                self.portfolio_snapshot_hash,
                "FixedIncomePortfolioRiskAssessment.portfolio_snapshot_hash",
            )
        if self.policy_hash is not None:
            _require_sha256(self.policy_hash, "FixedIncomePortfolioRiskAssessment.policy_hash")
        _require_aware(self.evaluated_at, "FixedIncomePortfolioRiskAssessment.evaluated_at")
        if self.input_hash is not None:
            _require_sha256(self.input_hash, "FixedIncomePortfolioRiskAssessment.input_hash")
        _require_sha256(self.output_hash, "FixedIncomePortfolioRiskAssessment.output_hash")
        if self.status is PortfolioRiskStatus.AVAILABLE and self.blockers:
            raise ValueError("available portfolio risk assessment cannot contain blockers")
        if self.status is PortfolioRiskStatus.BLOCKED and not self.blockers:
            raise ValueError("blocked portfolio risk assessment requires blockers")
        if (
            not self.research_only
            or not self.must_not_use_for_decision
            or not self.must_not_execute
        ):
            raise ValueError("portfolio risk assessment must remain research-only")
        if self.output_hash.lower() != self.calculated_output_hash:
            raise ValueError("portfolio risk assessment output_hash mismatch")

    @property
    def calculated_output_hash(self) -> str:
        """Return the canonical SHA-256 over the full assessment output."""

        return build_portfolio_risk_output_hash(
            status=self.status,
            bundle_id=self.bundle_id,
            portfolio_snapshot_id=self.portfolio_snapshot_id,
            portfolio_snapshot_hash=self.portfolio_snapshot_hash,
            policy_version=self.policy_version,
            policy_hash=self.policy_hash,
            evaluated_at=self.evaluated_at,
            input_hash=self.input_hash,
            totals=self.totals,
            position_contributions=self.position_contributions,
            stress_results=self.stress_results,
            blockers=self.blockers,
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )


def build_portfolio_risk_output_hash(
    *,
    status: PortfolioRiskStatus,
    bundle_id: str,
    portfolio_snapshot_id: str | None,
    portfolio_snapshot_hash: str | None,
    policy_version: str,
    policy_hash: str | None,
    evaluated_at: datetime,
    input_hash: str | None,
    totals: PortfolioRiskTotals | None,
    position_contributions: tuple[PositionRiskContribution, ...],
    stress_results: tuple[StressScenarioResult, ...],
    blockers: tuple[PortfolioRiskBlocker, ...],
    research_only: bool,
    must_not_use_for_decision: bool,
    must_not_execute: bool,
) -> str:
    """Build the canonical SHA-256 over a complete assessment output."""

    return _sha256_payload(
        {
            "status": status,
            "bundle_id": bundle_id,
            "portfolio_snapshot_id": portfolio_snapshot_id,
            "portfolio_snapshot_hash": portfolio_snapshot_hash,
            "policy_version": policy_version,
            "policy_hash": policy_hash,
            "evaluated_at": evaluated_at,
            "input_hash": input_hash,
            "totals": totals,
            "position_contributions": position_contributions,
            "stress_results": stress_results,
            "blockers": blockers,
            "research_only": research_only,
            "must_not_use_for_decision": must_not_use_for_decision,
            "must_not_execute": must_not_execute,
        }
    )


def blocked_fixed_income_portfolio_risk_assessment(
    *,
    bundle_id: str,
    policy_version: str,
    evaluated_at: datetime,
    blocker: PortfolioRiskBlocker,
    input_hash: str | None = None,
    portfolio_snapshot_id: str | None = None,
    portfolio_snapshot_hash: str | None = None,
    policy_hash: str | None = None,
) -> FixedIncomePortfolioRiskAssessment:
    """Build a sealed missing-evidence assessment for the Application boundary."""

    blockers = (blocker,)
    output_hash = build_portfolio_risk_output_hash(
        status=PortfolioRiskStatus.BLOCKED,
        bundle_id=bundle_id,
        portfolio_snapshot_id=portfolio_snapshot_id,
        portfolio_snapshot_hash=portfolio_snapshot_hash,
        policy_version=policy_version,
        policy_hash=policy_hash,
        evaluated_at=evaluated_at,
        input_hash=input_hash,
        totals=None,
        position_contributions=(),
        stress_results=(),
        blockers=blockers,
        research_only=True,
        must_not_use_for_decision=True,
        must_not_execute=True,
    )
    return FixedIncomePortfolioRiskAssessment(
        status=PortfolioRiskStatus.BLOCKED,
        bundle_id=bundle_id,
        portfolio_snapshot_id=portfolio_snapshot_id,
        portfolio_snapshot_hash=portfolio_snapshot_hash,
        policy_version=policy_version,
        policy_hash=policy_hash,
        evaluated_at=evaluated_at,
        input_hash=input_hash,
        totals=None,
        position_contributions=(),
        stress_results=(),
        blockers=blockers,
        output_hash=output_hash,
    )


def _block(
    code: PortfolioRiskBlockerCode,
    detail: str,
    *,
    position_id: str | None = None,
    scenario_id: str | None = None,
) -> PortfolioRiskBlocker:
    return PortfolioRiskBlocker(
        code=code,
        detail=detail,
        position_id=position_id,
        scenario_id=scenario_id,
    )


def _validate_evidence(
    bundle: PortfolioRiskInputBundle,
    policy: FixedIncomeRiskBudgetPolicy,
    evaluated_at: datetime,
) -> list[PortfolioRiskBlocker]:
    blockers: list[PortfolioRiskBlocker] = []
    if bundle.input_hash.lower() != bundle.calculated_input_hash:
        blockers.append(_block(PortfolioRiskBlockerCode.INPUT_HASH_MISMATCH, "input hash mismatch"))
    if bundle.budget_policy_version != policy.policy_version:
        blockers.append(
            _block(
                PortfolioRiskBlockerCode.BUNDLE_POLICY_MISMATCH, "budget policy version mismatch"
            )
        )
    if bundle.budget_policy_hash.lower() != policy.policy_hash.lower():
        blockers.append(
            _block(
                PortfolioRiskBlockerCode.POLICY_HASH_MISMATCH,
                "budget policy content hash mismatch",
            )
        )
    if policy.policy_hash.lower() != policy.calculated_policy_hash:
        blockers.append(
            _block(
                PortfolioRiskBlockerCode.POLICY_HASH_MISMATCH,
                "budget policy declared hash is invalid",
            )
        )
    if bundle.portfolio_snapshot_as_of != bundle.as_of:
        blockers.append(
            _block(
                PortfolioRiskBlockerCode.PORTFOLIO_SNAPSHOT_MISMATCH,
                "portfolio snapshot as_of does not match risk bundle",
            )
        )
    if bundle.currency != policy.currency:
        blockers.append(
            _block(PortfolioRiskBlockerCode.CURRENCY_MISMATCH, "policy currency mismatch")
        )
    if bundle.created_at > evaluated_at or bundle.as_of > evaluated_at:
        blockers.append(
            _block(PortfolioRiskBlockerCode.EVIDENCE_FROM_FUTURE, "bundle evidence is from future")
        )
    if bundle.valid_until <= evaluated_at:
        blockers.append(_block(PortfolioRiskBlockerCode.BUNDLE_STALE, "bundle evidence is stale"))
    if not policy.activated_at <= evaluated_at < policy.valid_until:
        blockers.append(
            _block(PortfolioRiskBlockerCode.POLICY_INACTIVE, "budget policy is inactive")
        )

    manifest = bundle.pit_manifest
    if manifest.manifest_hash.lower() != manifest.calculated_manifest_hash:
        blockers.append(
            _block(
                PortfolioRiskBlockerCode.PIT_MANIFEST_HASH_MISMATCH, "PIT manifest hash mismatch"
            )
        )
    if manifest.as_of != bundle.as_of:
        blockers.append(_block(PortfolioRiskBlockerCode.AS_OF_MISMATCH, "PIT as_of mismatch"))
    if manifest.observed_at > evaluated_at:
        blockers.append(
            _block(PortfolioRiskBlockerCode.EVIDENCE_FROM_FUTURE, "PIT manifest is from future")
        )
    if manifest.valid_until <= evaluated_at:
        blockers.append(
            _block(PortfolioRiskBlockerCode.PIT_MANIFEST_STALE, "PIT manifest is stale")
        )
    if (
        manifest.coverage_ratio != Decimal("1")
        or manifest.missing_count != 0
        or manifest.estimated_count != 0
        or manifest.unknown_count != 0
    ):
        blockers.append(
            _block(PortfolioRiskBlockerCode.PIT_MANIFEST_INCOMPLETE, "PIT manifest is incomplete")
        )

    referenced_identities: set[tuple[str, str, str]] = set()
    for position in bundle.positions:
        if position.as_of != bundle.as_of:
            blockers.append(
                _block(
                    PortfolioRiskBlockerCode.AS_OF_MISMATCH,
                    "position as_of mismatch",
                    position_id=position.position_id,
                )
            )
        if position.currency != bundle.currency:
            blockers.append(
                _block(
                    PortfolioRiskBlockerCode.CURRENCY_MISMATCH,
                    "position currency mismatch",
                    position_id=position.position_id,
                )
            )
        for reference in position.publication_references:
            referenced_identities.add(reference.identity)
            if (
                reference.subject_id != position.instrument_id
                or reference.currency != bundle.currency
            ):
                blockers.append(
                    _block(
                        PortfolioRiskBlockerCode.CURRENCY_MISMATCH,
                        "publication subject or currency mismatch",
                        position_id=position.position_id,
                    )
                )
            if reference.observed_at > bundle.as_of or reference.published_at > bundle.as_of:
                blockers.append(
                    _block(
                        PortfolioRiskBlockerCode.PUBLICATION_FROM_FUTURE,
                        "publication was unavailable at bundle as_of",
                        position_id=position.position_id,
                    )
                )
            if reference.valid_until <= evaluated_at:
                blockers.append(
                    _block(
                        PortfolioRiskBlockerCode.PUBLICATION_STALE,
                        "publication is stale",
                        position_id=position.position_id,
                    )
                )
    manifest_identities = {item.identity for item in manifest.publication_identities}
    if referenced_identities != manifest_identities:
        blockers.append(
            _block(
                PortfolioRiskBlockerCode.PUBLICATION_IDENTITY_MISMATCH,
                "position publications do not exactly match PIT manifest identities",
            )
        )

    canonical_tenors = {item.tenor_years for item in bundle.positions[0].key_rate_exposures}
    if any(
        {item.tenor_years for item in position.key_rate_exposures} != canonical_tenors
        for position in bundle.positions
    ):
        blockers.append(
            _block(
                PortfolioRiskBlockerCode.RATE_SHOCK_UNIVERSE_MISMATCH,
                "position key-rate universes do not match",
            )
        )
    credit_buckets = {
        position.credit_bucket
        for position in bundle.positions
        if position.credit_spread_duration_years > 0
    }
    for scenario in bundle.stress_scenarios:
        if {item.tenor_years for item in scenario.rate_shocks} != canonical_tenors:
            blockers.append(
                _block(
                    PortfolioRiskBlockerCode.RATE_SHOCK_UNIVERSE_MISMATCH,
                    "scenario does not explicitly cover the key-rate universe",
                    scenario_id=scenario.scenario_id,
                )
            )
        if {item.credit_bucket for item in scenario.credit_shocks} != credit_buckets:
            blockers.append(
                _block(
                    PortfolioRiskBlockerCode.CREDIT_SHOCK_UNIVERSE_MISMATCH,
                    "scenario does not explicitly cover the credit universe",
                    scenario_id=scenario.scenario_id,
                )
            )
    for position in bundle.positions:
        duration_sum = sum(
            (item.duration_years for item in position.key_rate_exposures),
            start=Decimal("0"),
        )
        if abs(duration_sum - position.modified_duration_years) > policy.identity_tolerance:
            blockers.append(
                _block(
                    PortfolioRiskBlockerCode.KEY_RATE_DURATION_IDENTITY_FAILED,
                    "key-rate durations do not sum to modified duration",
                    position_id=position.position_id,
                )
            )
        convexity_sum = sum(
            (item.convexity_years_squared for item in position.key_rate_exposures),
            start=Decimal("0"),
        )
        if abs(convexity_sum - position.convexity_years_squared) > policy.identity_tolerance:
            blockers.append(
                _block(
                    PortfolioRiskBlockerCode.KEY_RATE_CONVEXITY_IDENTITY_FAILED,
                    "key-rate convexities do not sum to total convexity",
                    position_id=position.position_id,
                )
            )
    return blockers


def _position_risk_contribution(
    position: FixedIncomePositionRiskInput,
) -> PositionRiskContribution:
    return PositionRiskContribution(
        position_id=position.position_id,
        market_value=position.market_value,
        dv01=position.market_value * position.modified_duration_years * _BASIS_POINT,
        cs01=position.market_value * position.credit_spread_duration_years * _BASIS_POINT,
        convexity_exposure=position.market_value * position.convexity_years_squared,
        liquidatable_value=position.market_value * position.liquidatable_fraction,
        liquidity_cost=position.market_value * position.liquidity_cost_rate,
    )


def _risk_totals(
    contributions: tuple[PositionRiskContribution, ...],
) -> PortfolioRiskTotals:
    market_value = sum((item.market_value for item in contributions), start=Decimal("0"))
    liquidatable_value = sum(
        (item.liquidatable_value for item in contributions),
        start=Decimal("0"),
    )
    return PortfolioRiskTotals(
        market_value=market_value,
        dv01=sum((item.dv01 for item in contributions), start=Decimal("0")),
        cs01=sum((item.cs01 for item in contributions), start=Decimal("0")),
        convexity_exposure=sum(
            (item.convexity_exposure for item in contributions),
            start=Decimal("0"),
        ),
        liquidatable_value=liquidatable_value,
        liquidatable_fraction=liquidatable_value / market_value,
        liquidity_cost=sum((item.liquidity_cost for item in contributions), start=Decimal("0")),
    )


from apps.fixed_income.domain.portfolio_risk_evaluation import (  # noqa: E402
    evaluate_fixed_income_portfolio_risk,
)

__all__ = [
    "CreditSpreadShock",
    "FixedIncomePortfolioRiskAssessment",
    "FixedIncomePositionRiskInput",
    "FixedIncomeRiskBudgetPolicy",
    "KeyRateExposure",
    "PITPublicationIdentity",
    "PortfolioRiskBlocker",
    "PortfolioRiskBlockerCode",
    "PortfolioRiskInputBundle",
    "PortfolioRiskPITManifest",
    "PortfolioRiskPublicationReference",
    "PortfolioRiskStatus",
    "PortfolioRiskTotals",
    "PortfolioStressScenario",
    "PositionRiskContribution",
    "PositionStressContribution",
    "PublicationRole",
    "RateShockKind",
    "RateShockPoint",
    "StressScenarioResult",
    "blocked_fixed_income_portfolio_risk_assessment",
    "build_fixed_income_risk_budget_policy_hash",
    "build_pit_manifest_hash",
    "build_portfolio_risk_input_hash",
    "build_portfolio_risk_output_hash",
    "evaluate_fixed_income_portfolio_risk",
]
