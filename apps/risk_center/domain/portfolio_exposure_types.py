"""Validated types for simulated portfolio industry and ETF exposure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)


class PortfolioAssetKind(StrEnum):
    """Supported direct assets in the simulated A-share portfolio projection."""

    EQUITY = "equity"
    ETF = "etf"


class ETFConstituentKind(StrEnum):
    """Explicit constituent kind used to keep cash separate from unknown assets."""

    EQUITY = "equity"
    CASH = "cash"
    OTHER = "other"


class EffectiveEndState(StrEnum):
    """Whether the membership source declares an open or bounded effective period."""

    OPEN = "open"
    BOUNDED = "bounded"
    UNKNOWN = "unknown"


class ExposureOutcome(StrEnum):
    """Explainable result of comparing known and possible industry exposure to policy."""

    WITHIN_LIMIT = "within_limit"
    LIMIT_BREACHED = "limit_breached"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class IndustryExposurePolicy:
    """Versioned limits and an explicit provider/taxonomy binding."""

    policy_id: str
    policy_version: str
    content_sha256: str
    taxonomy_id: str
    taxonomy_kind: str
    provider_id: str
    provider_version: str
    effective_from: datetime
    effective_until: datetime | None
    known_at: datetime
    requested_purpose: str
    date_precision_purposes: tuple[str, ...]
    allowed_observation_precisions: tuple[SourceObservationPrecision, ...]
    allowed_source_restrictions: tuple[str, ...]
    coverage_precision_basis: str
    max_industry_weight: Decimal
    max_security_weight: Decimal
    minimum_industry_coverage: Decimal
    minimum_etf_lookthrough_coverage: Decimal
    coverage_weight_tolerance: Decimal

    def __post_init__(self) -> None:
        for name, value in (
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
            ("taxonomy_id", self.taxonomy_id),
            ("provider_id", self.provider_id),
            ("provider_version", self.provider_version),
            ("requested_purpose", self.requested_purpose),
            ("coverage_precision_basis", self.coverage_precision_basis),
        ):
            _require_token(value, name)
        if (
            type(self.content_sha256) is not str
            or len(self.content_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.content_sha256)
        ):
            raise ValueError("content_sha256 must be a normalized policy SHA-256 digest")
        if type(self.date_precision_purposes) is not tuple or any(
            type(value) is not str or not value for value in self.date_precision_purposes
        ):
            raise ValueError("date_precision_purposes must be a tuple of purpose tokens")
        if any(
            value.strip() != value or any(character.isspace() for character in value)
            for value in self.date_precision_purposes
        ):
            raise ValueError("date_precision_purposes must use canonical tokens")
        if len(set(self.date_precision_purposes)) != len(self.date_precision_purposes):
            raise ValueError("date_precision_purposes cannot contain duplicates")
        if self.taxonomy_kind != "industry":
            raise ValueError("industry risk policy must bind taxonomy_kind='industry'")
        for clock_name, clock_value in (
            ("effective_from", self.effective_from),
            ("known_at", self.known_at),
        ):
            _require_aware(clock_value, clock_name)
        if self.effective_until is not None:
            _require_aware(self.effective_until, "effective_until")
        if self.effective_until is not None and self.effective_from >= self.effective_until:
            raise ValueError("industry risk policy effective window is invalid")
        if type(self.allowed_observation_precisions) is not tuple or not (
            self.allowed_observation_precisions
        ):
            raise ValueError("allowed_observation_precisions must be a nonempty tuple")
        if any(
            not isinstance(item, SourceObservationPrecision)
            for item in self.allowed_observation_precisions
        ):
            raise TypeError("allowed_observation_precisions contains an unsupported value")
        if len(set(self.allowed_observation_precisions)) != len(
            self.allowed_observation_precisions
        ):
            raise ValueError("allowed_observation_precisions cannot contain duplicates")
        if type(self.allowed_source_restrictions) is not tuple or any(
            type(value) is not str
            or not value
            or value.strip() != value
            or any(character.isspace() for character in value)
            for value in self.allowed_source_restrictions
        ):
            raise ValueError("allowed_source_restrictions must be canonical restriction tokens")
        if len(set(self.allowed_source_restrictions)) != len(self.allowed_source_restrictions):
            raise ValueError("allowed_source_restrictions cannot contain duplicates")
        if any(
            _is_unconditionally_prohibited_restriction(value)
            for value in self.allowed_source_restrictions
        ):
            raise ValueError("policy cannot allow an unconditional source prohibition")
        _require_fraction(self.max_industry_weight, "max_industry_weight", positive=True)
        _require_fraction(self.max_security_weight, "max_security_weight", positive=True)
        _require_fraction(self.minimum_industry_coverage, "minimum_industry_coverage")
        _require_fraction(
            self.minimum_etf_lookthrough_coverage,
            "minimum_etf_lookthrough_coverage",
        )
        _require_fraction(self.coverage_weight_tolerance, "coverage_weight_tolerance")


@dataclass(frozen=True, slots=True)
class IndustryMembership:
    """One source-bound membership in the policy's exact industry taxonomy."""

    taxonomy_id: str
    taxonomy_kind: str
    provider_id: str
    provider_version: str
    industry_code: str
    effective_from: date
    effective_end_state: EffectiveEndState
    source_evidence: PortfolioRiskSourceEvidence
    effective_until: date | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("taxonomy_id", self.taxonomy_id),
            ("taxonomy_kind", self.taxonomy_kind),
            ("provider_id", self.provider_id),
            ("provider_version", self.provider_version),
            ("industry_code", self.industry_code),
        ):
            _require_token(value, name)
        if type(self.effective_from) is not date:
            raise TypeError("effective_from must be a date")
        if self.effective_until is not None and type(self.effective_until) is not date:
            raise TypeError("effective_until must be a date or None")
        if not isinstance(self.effective_end_state, EffectiveEndState):
            raise TypeError("effective_end_state must be EffectiveEndState")
        if self.effective_end_state is EffectiveEndState.BOUNDED:
            if self.effective_until is None or self.effective_until < self.effective_from:
                raise ValueError("bounded membership requires a valid effective_until")
        elif self.effective_until is not None:
            raise ValueError("open or unknown membership cannot carry effective_until")
        if type(self.source_evidence) is not PortfolioRiskSourceEvidence:
            raise TypeError("source_evidence must be PortfolioRiskSourceEvidence")
        if (
            self.source_evidence.effective_on is not None
            and self.source_evidence.effective_on != self.effective_from
        ):
            raise ValueError("membership effective date differs from source evidence")
        if (
            self.source_evidence.effective_until is not None
            and self.source_evidence.effective_until != self.effective_until
        ):
            raise ValueError("membership end date differs from source evidence")


@dataclass(frozen=True, slots=True)
class ETFConstituent:
    """One exact constituent and its fraction of the ETF's reported net assets."""

    asset_code: str
    weight_fraction: Decimal
    kind: ETFConstituentKind
    industry_membership: IndustryMembership | None

    def __post_init__(self) -> None:
        _require_token(self.asset_code, "ETF constituent asset_code")
        _require_fraction(self.weight_fraction, "ETF constituent weight_fraction")
        if not isinstance(self.kind, ETFConstituentKind):
            raise TypeError("ETF constituent kind must be ETFConstituentKind")
        if self.industry_membership is not None and (
            type(self.industry_membership) is not IndustryMembership
            or self.kind is not ETFConstituentKind.EQUITY
        ):
            raise ValueError("only an equity constituent can carry industry membership")


@dataclass(frozen=True, slots=True)
class ETFConstituentReport:
    """One dated ETF holdings disclosure with explicit source evidence and coverage."""

    report_date: date
    source_evidence: PortfolioRiskSourceEvidence
    constituents: tuple[ETFConstituent, ...]

    def __post_init__(self) -> None:
        if type(self.report_date) is not date:
            raise TypeError("report_date must be a date")
        if type(self.source_evidence) is not PortfolioRiskSourceEvidence:
            raise TypeError("source_evidence must be PortfolioRiskSourceEvidence")
        if type(self.constituents) is not tuple or any(
            type(row) is not ETFConstituent for row in self.constituents
        ):
            raise TypeError("constituents must be a tuple of ETFConstituent")
        if self.source_evidence.effective_on not in {None, self.report_date}:
            raise ValueError("ETF report date differs from its source effective date")
        asset_codes = tuple(row.asset_code for row in self.constituents)
        if len(asset_codes) != len(set(asset_codes)):
            raise ValueError("ETF constituent report contains duplicate asset codes")
        if sum((row.weight_fraction for row in self.constituents), Decimal("0")) > 1:
            raise ValueError("ETF constituent weights cannot exceed the ETF net asset value")


@dataclass(frozen=True, slots=True)
class PortfolioRiskAsset:
    """One projected direct asset after existing holdings/orders were aggregated."""

    asset_code: str
    kind: PortfolioAssetKind
    projected_market_value: Decimal | None
    valuation_evidence: PortfolioRiskSourceEvidence | None
    industry_membership: IndustryMembership | None
    etf_report: ETFConstituentReport | None

    def __post_init__(self) -> None:
        _require_token(self.asset_code, "asset_code")
        if not isinstance(self.kind, PortfolioAssetKind):
            raise TypeError("kind must be PortfolioAssetKind")
        if self.projected_market_value is not None and (
            type(self.projected_market_value) is not Decimal
            or not self.projected_market_value.is_finite()
            or self.projected_market_value < 0
        ):
            raise ValueError("projected_market_value must be a finite nonnegative Decimal")
        if self.valuation_evidence is not None and (
            type(self.valuation_evidence) is not PortfolioRiskSourceEvidence
        ):
            raise TypeError("valuation_evidence must be PortfolioRiskSourceEvidence or None")
        if self.industry_membership is not None and (
            type(self.industry_membership) is not IndustryMembership
        ):
            raise TypeError("industry_membership must be IndustryMembership or None")
        if self.etf_report is not None and type(self.etf_report) is not ETFConstituentReport:
            raise TypeError("etf_report must be ETFConstituentReport or None")
        if self.kind is PortfolioAssetKind.EQUITY and self.etf_report is not None:
            raise ValueError("equity asset cannot carry an ETF constituent report")
        if self.kind is PortfolioAssetKind.ETF and self.industry_membership is not None:
            raise ValueError("ETF issuer classification cannot replace look-through exposure")


@dataclass(frozen=True, slots=True)
class PortfolioExposureProjection:
    """One account projection at an exact cutoff, assembled by its owning context."""

    portfolio_snapshot_id: str
    as_of: datetime
    business_date: date
    portfolio_market_value: Decimal | None
    assets: tuple[PortfolioRiskAsset, ...]

    def __post_init__(self) -> None:
        _require_token(self.portfolio_snapshot_id, "portfolio_snapshot_id")
        _require_aware(self.as_of, "as_of")
        if type(self.business_date) is not date:
            raise TypeError("business_date must be a date")
        if self.portfolio_market_value is not None and (
            type(self.portfolio_market_value) is not Decimal
            or not self.portfolio_market_value.is_finite()
            or self.portfolio_market_value <= 0
        ):
            raise ValueError("portfolio_market_value must be a finite positive Decimal or None")
        if type(self.assets) is not tuple or any(
            type(asset) is not PortfolioRiskAsset for asset in self.assets
        ):
            raise TypeError("assets must be a tuple of PortfolioRiskAsset")
        codes = tuple(asset.asset_code for asset in self.assets)
        if len(codes) != len(set(codes)):
            raise ValueError("projected assets must be aggregated by asset_code")


@dataclass(frozen=True, slots=True)
class IndustryExposureBound:
    """Known lower and conservative possible upper exposure for one industry."""

    industry_code: str
    known_market_value: Decimal
    unknown_market_value: Decimal | None
    lower_weight: Decimal | None
    upper_weight: Decimal | None
    maximum_weight: Decimal
    outcome: ExposureOutcome


@dataclass(frozen=True, slots=True)
class ETFIndustryExposureBound:
    """One ETF's industry lower bound plus its non-duplicated unknown remainder."""

    industry_code: str
    known_market_value: Decimal
    unknown_market_value: Decimal
    upper_market_value: Decimal


@dataclass(frozen=True, slots=True)
class ETFExposureBound:
    """Per-ETF classified exposure and the real remainder that may hit one industry."""

    asset_code: str
    report_date: date | None
    coverage_status: CoverageStatus | None
    reported_coverage_fraction: Decimal | None
    known_industry_market_value: Decimal
    unknown_market_value: Decimal | None
    maximum_industry_market_value: Decimal | None
    industry_bounds: tuple[ETFIndustryExposureBound, ...]
    known_security_market_value: Decimal
    unknown_security_market_value: Decimal | None
    maximum_security_market_value: Decimal | None
    source_id: str | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RepeatedUnderlyingExposure:
    """One stock held directly and through one or more ETF disclosures."""

    asset_code: str
    direct_market_value: Decimal
    etf_market_value: Decimal
    etf_asset_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SecurityExposureBound:
    """Known direct/ETF exposure plus all source-bounded unknown security remainder."""

    asset_code: str
    direct_market_value: Decimal
    etf_lookthrough_market_value: Decimal
    known_market_value: Decimal
    unknown_market_value: Decimal | None
    lower_weight: Decimal | None
    upper_weight: Decimal | None
    maximum_weight: Decimal
    etf_asset_codes: tuple[str, ...]
    outcome: ExposureOutcome


@dataclass(frozen=True, slots=True)
class PortfolioIndustryExposureAssessment:
    """Explainable portfolio exposure bounds without substituting unknown with zero."""

    portfolio_snapshot_id: str
    policy_id: str
    policy_version: str
    policy_content_sha256: str
    as_of: datetime
    outcome: ExposureOutcome
    industry_bounds: tuple[IndustryExposureBound, ...]
    security_bounds: tuple[SecurityExposureBound, ...]
    etf_bounds: tuple[ETFExposureBound, ...]
    repeated_underlyings: tuple[RepeatedUnderlyingExposure, ...]
    unknown_industry_market_value: Decimal | None
    unknown_security_market_value: Decimal | None
    industry_coverage_fraction: Decimal | None
    etf_lookthrough_coverage_fraction: Decimal | None
    reason_codes: tuple[str, ...]
    source_ids: tuple[str, ...]
    source_evidence: tuple[PortfolioRiskSourceEvidence, ...]


def _is_unconditionally_prohibited_restriction(value: str) -> bool:
    normalized = value.lower()
    return (
        normalized.startswith("must_not_")
        or normalized.startswith("research_only")
        or normalized.startswith("observation_only")
    )


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


def _require_fraction(value: Decimal, field_name: str, *, positive: bool = False) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise TypeError(f"{field_name} must be an exact finite Decimal")
    if value < 0 or value > 1 or (positive and value == 0):
        raise ValueError(f"{field_name} must be within the configured unit interval")


def _require_token(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a nonempty canonical token")


__all__ = (
    "ETFConstituent",
    "ETFConstituentKind",
    "ETFConstituentReport",
    "ETFExposureBound",
    "ETFIndustryExposureBound",
    "EffectiveEndState",
    "ExposureOutcome",
    "IndustryExposureBound",
    "IndustryExposurePolicy",
    "IndustryMembership",
    "PortfolioAssetKind",
    "PortfolioExposureProjection",
    "PortfolioIndustryExposureAssessment",
    "PortfolioRiskAsset",
    "RepeatedUnderlyingExposure",
    "SecurityExposureBound",
)
