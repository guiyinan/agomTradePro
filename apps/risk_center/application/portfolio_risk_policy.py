"""Typed read model and strict parser for the simulation-only portfolio-risk policy."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol, cast

from apps.risk_center.domain.portfolio_capacity import (
    CapacityBasis,
    CapacityMeasure,
    CapacityParticipationPolicy,
    CapacityUsageDateBasis,
    CapacityUsageScope,
    CapacityWindowKind,
)
from apps.risk_center.domain.portfolio_exposure_types import (
    IndustryExposurePolicy,
)
from apps.risk_center.domain.portfolio_risk_sources import SourceObservationPrecision
from core.integration.config_center_runtime import ActiveRuntimeValueEvidence

SIMULATED_PORTFOLIO_RISK_SCHEMA = "ash07.simulated_portfolio_risk.v1"
SIMULATED_PORTFOLIO_RISK_SCOPE = "simulation_only"
SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY = "risk_center.simulated_portfolio_risk"

PolicySourceKind = Literal[
    "valuation",
    "industry_membership",
    "etf_report",
    "capacity_window",
    "execution_session_state",
]

_SOURCE_KINDS: frozenset[str] = frozenset(
    {
        "valuation",
        "industry_membership",
        "etf_report",
        "capacity_window",
        "execution_session_state",
    }
)
_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "scope",
        "ledger_money_unit",
        "account_ids",
        "industry",
        "capacity",
        "source_max_timestamp_age_seconds",
        "source_max_date_age_days",
        "source_references",
    }
)
_INDUSTRY_KEYS: frozenset[str] = frozenset(
    {
        "taxonomy_id",
        "taxonomy_kind",
        "provider_id",
        "provider_version",
        "requested_purpose",
        "date_precision_purposes",
        "allowed_observation_precisions",
        "allowed_source_restrictions",
        "coverage_precision_basis",
        "max_industry_weight",
        "max_security_weight",
        "minimum_industry_coverage",
        "minimum_etf_lookthrough_coverage",
        "coverage_weight_tolerance",
    }
)
_CAPACITY_KEYS: frozenset[str] = frozenset(
    {
        "measure",
        "unit",
        "basis",
        "usage_scope",
        "date_basis",
        "max_participation",
        "increment",
        "window_kind",
        "sessions",
        "allowed_observation_precisions",
        "date_precision_purposes",
        "allowed_source_restrictions",
    }
)
_SOURCE_REFERENCE_KEYS: frozenset[str] = frozenset(
    {"kind", "asset_code", "security_id", "raw_payload_hash", "source_record_id"}
)
_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class PortfolioRiskPolicyConfigurationError(ValueError):
    """One malformed or unsupported simulation-risk runtime configuration."""

    def __init__(self, reason_code: str, message: str) -> None:
        """Expose one stable reason for the read result while preserving detail."""

        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PortfolioRiskSourceReference:
    """One policy-approved, source-record-bound input reference."""

    kind: PolicySourceKind
    asset_code: str
    security_id: str
    raw_payload_hash: str
    source_record_id: str

    def __post_init__(self) -> None:
        """Validate the exact source kind, identities, and prefixed raw hash."""

        if self.kind not in _SOURCE_KINDS:
            raise ValueError("source reference kind is unsupported")
        _required_token(self.asset_code, "source reference asset_code")
        _required_token(self.security_id, "source reference security_id")
        _required_token(self.source_record_id, "source reference source_record_id")
        if (
            type(self.raw_payload_hash) is not str
            or _HASH_PATTERN.fullmatch(self.raw_payload_hash) is None
        ):
            raise ValueError("source reference raw_payload_hash must be sha256:<64 lowercase hex>")


@dataclass(frozen=True, slots=True)
class PortfolioRiskPolicyBundle:
    """One profile-bound policy pair with shared identity, clocks, and content digest."""

    schema_version: str
    scope: str
    ledger_money_unit: str
    account_ids: tuple[int, ...]
    industry_policy: IndustryExposurePolicy
    capacity_policy: CapacityParticipationPolicy
    source_max_timestamp_age_seconds: int
    source_max_date_age_days: int
    source_references: tuple[PortfolioRiskSourceReference, ...]
    environment: str
    profile_id: str
    profile_key: str
    profile_version: int
    profile_content_hash: str
    snapshot_id: str
    snapshot_hash: str
    normalized_config_sha256: str
    created_at: datetime
    known_at: datetime
    activated_at: datetime
    snapshot_generated_at: datetime
    effective_at: datetime
    business_date: date
    as_of: datetime

    def __post_init__(self) -> None:
        """Ensure both sub-policies carry this exact runtime/content identity."""

        if self.schema_version != SIMULATED_PORTFOLIO_RISK_SCHEMA:
            raise ValueError("schema_version is unsupported")
        if self.scope != SIMULATED_PORTFOLIO_RISK_SCOPE:
            raise ValueError("policy scope must be simulation_only")
        _required_token(self.ledger_money_unit, "ledger_money_unit")
        if type(self.account_ids) is not tuple or not self.account_ids:
            raise ValueError("account_ids must be a nonempty tuple")
        if any(type(account_id) is not int or account_id < 1 for account_id in self.account_ids):
            raise ValueError("account_ids must contain positive exact integers")
        if len(set(self.account_ids)) != len(self.account_ids):
            raise ValueError("account_ids cannot contain duplicates")
        if type(self.source_references) is not tuple or not self.source_references:
            raise ValueError("source_references must be a nonempty tuple")
        if any(
            type(reference) is not PortfolioRiskSourceReference
            for reference in self.source_references
        ):
            raise TypeError("source_references must contain typed source references")
        if type(self.source_max_timestamp_age_seconds) is not int or (
            self.source_max_timestamp_age_seconds < 0
        ):
            raise ValueError("source_max_timestamp_age_seconds must be a nonnegative integer")
        if type(self.source_max_date_age_days) is not int or self.source_max_date_age_days < 0:
            raise ValueError("source_max_date_age_days must be a nonnegative integer")
        for name, value in (
            ("environment", self.environment),
            ("profile_id", self.profile_id),
            ("profile_key", self.profile_key),
        ):
            _required_token(value, name)
        if type(self.profile_version) is not int or self.profile_version < 1:
            raise ValueError("profile_version must be a positive integer")
        for name, value in (
            ("profile_content_hash", self.profile_content_hash),
            ("snapshot_hash", self.snapshot_hash),
            ("normalized_config_sha256", self.normalized_config_sha256),
        ):
            if type(value) is not str or _DIGEST_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        _required_token(self.snapshot_id, "snapshot_id")
        for clock_name, clock_value in (
            ("created_at", self.created_at),
            ("known_at", self.known_at),
            ("activated_at", self.activated_at),
            ("snapshot_generated_at", self.snapshot_generated_at),
            ("effective_at", self.effective_at),
            ("as_of", self.as_of),
        ):
            _require_aware(clock_value, clock_name)
        if type(self.business_date) is not date:
            raise TypeError("business_date must be a date")
        if self.activated_at != self.effective_at:
            raise ValueError("runtime profile activation and snapshot effective clocks differ")
        if self.known_at != max(self.created_at, self.snapshot_generated_at, self.effective_at):
            raise ValueError("known_at must be the conservative maximum of actual runtime clocks")
        if self.effective_at > self.as_of or self.known_at > self.as_of:
            raise ValueError("runtime policy evidence is not effective and known at cutoff")
        policy_id = self.profile_id
        policy_version = str(self.profile_version)
        if (
            self.industry_policy.policy_id != policy_id
            or self.industry_policy.policy_version != policy_version
            or self.industry_policy.content_sha256 != self.normalized_config_sha256
            or self.industry_policy.effective_from != self.effective_at
            or self.industry_policy.effective_until is not None
            or self.industry_policy.known_at != self.known_at
        ):
            raise ValueError("industry policy runtime identity differs from its bundle")
        if (
            self.capacity_policy.policy_id != policy_id
            or self.capacity_policy.version != policy_version
            or self.capacity_policy.content_hash != self.normalized_config_sha256
            or self.capacity_policy.effective_from != self.effective_at
            or self.capacity_policy.effective_until is not None
            or self.capacity_policy.known_at != self.known_at
        ):
            raise ValueError("capacity policy runtime identity differs from its bundle")


@dataclass(frozen=True, slots=True)
class PortfolioRiskPolicyReadResult:
    """Successful policy bundle or a stable fail-closed read reason."""

    policy: PortfolioRiskPolicyBundle | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Keep result presence consistent with its stable reason codes."""

        if type(self.reason_codes) is not tuple or any(
            type(reason) is not str or not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must be a tuple of stable nonempty tokens")
        if (self.policy is None) == (not self.reason_codes):
            raise ValueError("policy result must contain exactly a policy or failure reasons")


@dataclass(frozen=True, slots=True)
class _IndustryPolicySettings:
    """Validated settings parsed from the industry section, before metadata binding."""

    taxonomy_id: str
    taxonomy_kind: str
    provider_id: str
    provider_version: str
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


@dataclass(frozen=True, slots=True)
class _CapacityPolicySettings:
    """Validated settings parsed from the capacity section, before metadata binding."""

    measure: CapacityMeasure
    unit: str
    capacity_basis: CapacityBasis
    usage_scope: CapacityUsageScope
    usage_date_basis: CapacityUsageDateBasis
    max_participation: Decimal
    capacity_increment: Decimal
    window_kind: CapacityWindowKind
    window_sessions: int
    allowed_observation_precisions: tuple[SourceObservationPrecision, ...]
    date_precision_purposes: tuple[str, ...]
    allowed_source_restrictions: tuple[str, ...]


class PortfolioRiskPolicyReader(Protocol):
    """Read one current policy for the requested simulation account and cutoff."""

    def read_policy(
        self,
        *,
        as_of: datetime,
        business_date: date,
        account_id: int,
    ) -> PortfolioRiskPolicyReadResult:
        """Return the scoped active policy or a typed fail-closed reason."""


def parse_portfolio_risk_policy_bundle(
    runtime_evidence: ActiveRuntimeValueEvidence,
    *,
    business_date: date,
    as_of: datetime,
) -> PortfolioRiskPolicyBundle:
    """Parse the exact JSON schema and derive policy identity only from runtime evidence."""

    if type(runtime_evidence) is not ActiveRuntimeValueEvidence:
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_RUNTIME_EVIDENCE_INVALID",
            "runtime_evidence must be ActiveRuntimeValueEvidence",
        )
    if type(business_date) is not date:
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_REQUEST_INVALID",
            "business_date must be an exact date",
        )
    try:
        _validate_runtime_evidence(runtime_evidence, as_of=as_of)
        raw = _require_mapping(runtime_evidence.value, "policy")
        _require_exact_keys(raw, _TOP_LEVEL_KEYS, "policy")
        schema_version = _required_token(raw["schema_version"], "schema_version")
        if schema_version != SIMULATED_PORTFOLIO_RISK_SCHEMA:
            raise PortfolioRiskPolicyConfigurationError(
                "SIMULATED_PORTFOLIO_RISK_SCHEMA_UNSUPPORTED",
                "schema_version is unsupported",
            )
        scope = _required_token(raw["scope"], "scope")
        if scope != SIMULATED_PORTFOLIO_RISK_SCOPE:
            raise PortfolioRiskPolicyConfigurationError(
                "SIMULATED_PORTFOLIO_RISK_SCOPE_UNSUPPORTED",
                "scope must be simulation_only",
            )
        ledger_money_unit = _required_token(raw["ledger_money_unit"], "ledger_money_unit")

        account_ids = _parse_account_ids(raw["account_ids"])
        industry_raw = _require_mapping(raw["industry"], "industry")
        capacity_raw = _require_mapping(raw["capacity"], "capacity")
        source_age_seconds = _nonnegative_integer(
            raw["source_max_timestamp_age_seconds"],
            "source_max_timestamp_age_seconds",
        )
        source_age_days = _nonnegative_integer(
            raw["source_max_date_age_days"],
            "source_max_date_age_days",
        )
        source_references = _parse_source_references(raw["source_references"])

        industry_values, normalized_industry = _parse_industry_values(industry_raw)
        capacity_values, normalized_capacity = _parse_capacity_values(capacity_raw)
        if capacity_values.measure == "amount" and capacity_values.unit != ledger_money_unit:
            raise PortfolioRiskPolicyConfigurationError(
                "SIMULATED_PORTFOLIO_RISK_CAPACITY_UNIT_MISMATCH",
                "amount capacity unit must match ledger_money_unit",
            )
        normalized_config = _normalized_config(
            schema_version=schema_version,
            scope=scope,
            ledger_money_unit=ledger_money_unit,
            account_ids=account_ids,
            industry=normalized_industry,
            capacity=normalized_capacity,
            source_max_timestamp_age_seconds=source_age_seconds,
            source_max_date_age_days=source_age_days,
            source_references=source_references,
        )
        content_digest = _canonical_sha256(normalized_config)

        known_at = max(
            runtime_evidence.created_at,
            runtime_evidence.snapshot_generated_at,
            runtime_evidence.effective_at,
        )
        profile_version = runtime_evidence.profile_version
        policy_id = runtime_evidence.profile_id
        policy_version = str(profile_version)
        try:
            industry_policy = IndustryExposurePolicy(
                policy_id=policy_id,
                policy_version=policy_version,
                content_sha256=content_digest,
                taxonomy_id=industry_values.taxonomy_id,
                taxonomy_kind=industry_values.taxonomy_kind,
                provider_id=industry_values.provider_id,
                provider_version=industry_values.provider_version,
                effective_from=runtime_evidence.effective_at,
                effective_until=None,
                known_at=known_at,
                requested_purpose=industry_values.requested_purpose,
                date_precision_purposes=industry_values.date_precision_purposes,
                allowed_observation_precisions=industry_values.allowed_observation_precisions,
                allowed_source_restrictions=industry_values.allowed_source_restrictions,
                coverage_precision_basis=industry_values.coverage_precision_basis,
                max_industry_weight=industry_values.max_industry_weight,
                max_security_weight=industry_values.max_security_weight,
                minimum_industry_coverage=industry_values.minimum_industry_coverage,
                minimum_etf_lookthrough_coverage=(industry_values.minimum_etf_lookthrough_coverage),
                coverage_weight_tolerance=industry_values.coverage_weight_tolerance,
            )
        except (TypeError, ValueError) as exc:
            raise PortfolioRiskPolicyConfigurationError(
                "SIMULATED_PORTFOLIO_RISK_INDUSTRY_POLICY_INVALID",
                "industry policy fields are invalid",
            ) from exc
        try:
            capacity_policy = CapacityParticipationPolicy(
                policy_id=policy_id,
                version=policy_version,
                content_hash=content_digest,
                measure=capacity_values.measure,
                unit=capacity_values.unit,
                capacity_basis=capacity_values.capacity_basis,
                usage_scope=capacity_values.usage_scope,
                usage_date_basis=capacity_values.usage_date_basis,
                max_participation=capacity_values.max_participation,
                capacity_increment=capacity_values.capacity_increment,
                window_kind=capacity_values.window_kind,
                window_sessions=capacity_values.window_sessions,
                effective_from=runtime_evidence.effective_at,
                effective_until=None,
                known_at=known_at,
                allowed_observation_precisions=(capacity_values.allowed_observation_precisions),
                date_precision_purposes=capacity_values.date_precision_purposes,
                allowed_source_restrictions=capacity_values.allowed_source_restrictions,
            )
        except (TypeError, ValueError) as exc:
            raise PortfolioRiskPolicyConfigurationError(
                "SIMULATED_PORTFOLIO_RISK_CAPACITY_POLICY_INVALID",
                "capacity policy fields are invalid",
            ) from exc

        try:
            return PortfolioRiskPolicyBundle(
                schema_version=schema_version,
                scope=scope,
                ledger_money_unit=ledger_money_unit,
                account_ids=account_ids,
                industry_policy=industry_policy,
                capacity_policy=capacity_policy,
                source_max_timestamp_age_seconds=source_age_seconds,
                source_max_date_age_days=source_age_days,
                source_references=source_references,
                environment=runtime_evidence.environment,
                profile_id=runtime_evidence.profile_id,
                profile_key=runtime_evidence.profile_key,
                profile_version=profile_version,
                profile_content_hash=runtime_evidence.profile_content_hash,
                snapshot_id=runtime_evidence.snapshot_id,
                snapshot_hash=runtime_evidence.snapshot_hash,
                normalized_config_sha256=content_digest,
                created_at=runtime_evidence.created_at,
                known_at=known_at,
                activated_at=runtime_evidence.activated_at,
                snapshot_generated_at=runtime_evidence.snapshot_generated_at,
                effective_at=runtime_evidence.effective_at,
                business_date=business_date,
                as_of=as_of,
            )
        except (TypeError, ValueError) as exc:
            raise PortfolioRiskPolicyConfigurationError(
                "SIMULATED_PORTFOLIO_RISK_RUNTIME_IDENTITY_INVALID",
                "runtime identity and policy bundle are inconsistent",
            ) from exc
    except PortfolioRiskPolicyConfigurationError:
        raise
    except (InvalidOperation, TypeError, ValueError, OverflowError) as exc:
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_CONFIGURATION_INVALID",
            "policy JSON does not satisfy its strict typed schema",
        ) from exc


def _validate_runtime_evidence(
    evidence: ActiveRuntimeValueEvidence,
    *,
    as_of: datetime,
) -> None:
    clocks = (
        evidence.created_at,
        evidence.known_at,
        evidence.activated_at,
        evidence.snapshot_generated_at,
        evidence.effective_at,
        evidence.as_of,
    )
    if any(not _is_aware(value) for value in clocks):
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_RUNTIME_EVIDENCE_INVALID",
            "runtime profile and snapshot clocks must be aware",
        )
    if not _is_aware(as_of) or evidence.as_of != as_of:
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_CUTOFF_MISMATCH",
            "runtime evidence was read at a different cutoff",
        )
    if evidence.activated_at != evidence.effective_at:
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_RUNTIME_EVIDENCE_INVALID",
            "profile activation and snapshot effective clocks differ",
        )
    if evidence.definition_key != SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY:
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_RUNTIME_EVIDENCE_INVALID",
            "runtime evidence came from a different definition key",
        )
    if type(evidence.environment) is not str or not evidence.environment.strip():
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_RUNTIME_EVIDENCE_INVALID",
            "runtime evidence has no environment identity",
        )
    if evidence.known_at != evidence.created_at:
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_RUNTIME_EVIDENCE_INVALID",
            "known_at must preserve the persisted profile creation clock",
        )
    if max(evidence.created_at, evidence.snapshot_generated_at, evidence.effective_at) > as_of:
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_RUNTIME_NOT_CURRENT_AT_CUTOFF",
            "runtime profile or snapshot is newer than the cutoff",
        )
    for field_name, value in (
        ("profile_content_hash", evidence.profile_content_hash),
        ("snapshot_hash", evidence.snapshot_hash),
    ):
        if type(value) is not str or _DIGEST_PATTERN.fullmatch(value) is None:
            raise PortfolioRiskPolicyConfigurationError(
                "SIMULATED_PORTFOLIO_RISK_RUNTIME_EVIDENCE_INVALID",
                f"{field_name} is not a lowercase SHA-256 digest",
            )


def _parse_account_ids(raw: object) -> tuple[int, ...]:
    if type(raw) is not list or not raw:
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_ACCOUNT_SCOPE_INVALID",
            "account_ids must be a nonempty JSON array",
        )
    account_ids = tuple(_positive_integer(value, "account_ids") for value in raw)
    if len(set(account_ids)) != len(account_ids):
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_ACCOUNT_SCOPE_INVALID",
            "account_ids contains duplicates",
        )
    return tuple(sorted(account_ids))


def _parse_source_references(raw: object) -> tuple[PortfolioRiskSourceReference, ...]:
    if type(raw) is not list or not raw:
        raise PortfolioRiskPolicyConfigurationError(
            "SIMULATED_PORTFOLIO_RISK_SOURCE_REFERENCES_INVALID",
            "source_references must be a nonempty JSON array",
        )
    references: list[PortfolioRiskSourceReference] = []
    identities: set[tuple[str, str, str]] = set()
    for item in raw:
        try:
            source = _require_mapping(item, "source reference")
            _require_exact_keys(source, _SOURCE_REFERENCE_KEYS, "source reference")
            kind = _required_token(source["kind"], "source reference.kind")
            if kind not in _SOURCE_KINDS:
                raise PortfolioRiskPolicyConfigurationError(
                    "SIMULATED_PORTFOLIO_RISK_SOURCE_KIND_UNSUPPORTED",
                    "source reference kind is unsupported",
                )
            raw_hash = _required_string(source["raw_payload_hash"], "raw_payload_hash")
            if _HASH_PATTERN.fullmatch(raw_hash) is None:
                raise PortfolioRiskPolicyConfigurationError(
                    "SIMULATED_PORTFOLIO_RISK_SOURCE_HASH_INVALID",
                    "raw_payload_hash must use sha256:<64 lowercase hex>",
                )
            reference = PortfolioRiskSourceReference(
                kind=cast(PolicySourceKind, kind),
                asset_code=_required_token(source["asset_code"], "asset_code"),
                security_id=_required_token(source["security_id"], "security_id"),
                raw_payload_hash=raw_hash,
                source_record_id=_required_token(source["source_record_id"], "source_record_id"),
            )
        except PortfolioRiskPolicyConfigurationError:
            raise
        except (TypeError, ValueError) as exc:
            raise PortfolioRiskPolicyConfigurationError(
                "SIMULATED_PORTFOLIO_RISK_SOURCE_REFERENCES_INVALID",
                "source reference fields are invalid",
            ) from exc
        identity = (reference.kind, reference.asset_code, reference.security_id)
        if identity in identities:
            raise PortfolioRiskPolicyConfigurationError(
                "SIMULATED_PORTFOLIO_RISK_SOURCE_REFERENCE_DUPLICATE",
                "source reference kind, asset and security identity is duplicated",
            )
        identities.add(identity)
        references.append(reference)
    return tuple(
        sorted(references, key=lambda item: (item.kind, item.asset_code, item.security_id))
    )


def _parse_industry_values(
    raw: Mapping[str, object],
) -> tuple[_IndustryPolicySettings, dict[str, object]]:
    _require_exact_keys(raw, _INDUSTRY_KEYS, "industry")
    precision_values = _precision_tuple(raw["allowed_observation_precisions"])
    date_purposes = _token_tuple(
        raw["date_precision_purposes"],
        "date_precision_purposes",
        allow_empty=True,
    )
    restrictions = _token_tuple(
        raw["allowed_source_restrictions"],
        "allowed_source_restrictions",
        allow_empty=True,
    )
    decimal_fields = (
        "max_industry_weight",
        "max_security_weight",
        "minimum_industry_coverage",
        "minimum_etf_lookthrough_coverage",
        "coverage_weight_tolerance",
    )
    decimals = {name: _decimal_text(raw[name], f"industry.{name}") for name in decimal_fields}
    values = _IndustryPolicySettings(
        taxonomy_id=_required_token(raw["taxonomy_id"], "taxonomy_id"),
        taxonomy_kind=_required_token(raw["taxonomy_kind"], "taxonomy_kind"),
        provider_id=_required_token(raw["provider_id"], "provider_id"),
        provider_version=_required_token(raw["provider_version"], "provider_version"),
        requested_purpose=_required_token(raw["requested_purpose"], "requested_purpose"),
        date_precision_purposes=date_purposes,
        allowed_observation_precisions=precision_values,
        allowed_source_restrictions=restrictions,
        coverage_precision_basis=_required_token(
            raw["coverage_precision_basis"],
            "coverage_precision_basis",
        ),
        max_industry_weight=decimals["max_industry_weight"],
        max_security_weight=decimals["max_security_weight"],
        minimum_industry_coverage=decimals["minimum_industry_coverage"],
        minimum_etf_lookthrough_coverage=decimals["minimum_etf_lookthrough_coverage"],
        coverage_weight_tolerance=decimals["coverage_weight_tolerance"],
    )
    normalized: dict[str, object] = {
        "taxonomy_id": values.taxonomy_id,
        "taxonomy_kind": values.taxonomy_kind,
        "provider_id": values.provider_id,
        "provider_version": values.provider_version,
        "requested_purpose": values.requested_purpose,
        "coverage_precision_basis": values.coverage_precision_basis,
        "max_industry_weight": _canonical_decimal_text(values.max_industry_weight),
        "max_security_weight": _canonical_decimal_text(values.max_security_weight),
        "minimum_industry_coverage": _canonical_decimal_text(values.minimum_industry_coverage),
        "minimum_etf_lookthrough_coverage": _canonical_decimal_text(
            values.minimum_etf_lookthrough_coverage
        ),
        "coverage_weight_tolerance": _canonical_decimal_text(values.coverage_weight_tolerance),
    }
    normalized["allowed_observation_precisions"] = sorted(
        precision.value for precision in precision_values
    )
    normalized["date_precision_purposes"] = sorted(date_purposes)
    normalized["allowed_source_restrictions"] = sorted(restrictions)
    return values, normalized


def _parse_capacity_values(
    raw: Mapping[str, object],
) -> tuple[_CapacityPolicySettings, dict[str, object]]:
    _require_exact_keys(raw, _CAPACITY_KEYS, "capacity")
    precision_values = _precision_tuple(raw["allowed_observation_precisions"])
    date_purposes = _token_tuple(
        raw["date_precision_purposes"],
        "date_precision_purposes",
        allow_empty=True,
    )
    restrictions = _token_tuple(
        raw["allowed_source_restrictions"],
        "allowed_source_restrictions",
        allow_empty=True,
    )
    measure = _required_token(raw["measure"], "measure")
    unit = _required_token(raw["unit"], "unit")
    basis = _required_token(raw["basis"], "basis")
    usage_scope = _required_token(raw["usage_scope"], "usage_scope")
    date_basis = _required_token(raw["date_basis"], "date_basis")
    window_kind = _required_token(raw["window_kind"], "window_kind")
    sessions = _positive_integer(raw["sessions"], "sessions")
    participation = _decimal_text(raw["max_participation"], "capacity.max_participation")
    increment = _decimal_text(raw["increment"], "capacity.increment")
    if measure not in ("volume", "amount"):
        raise ValueError("capacity.measure is unsupported")
    if basis not in ("session_total", "average_per_session"):
        raise ValueError("capacity.basis is unsupported")
    if usage_scope != "account_security_session":
        raise ValueError("capacity.usage_scope is unsupported")
    if date_basis != "execution_session":
        raise ValueError("capacity.date_basis is unsupported")
    if window_kind not in ("session_cumulative", "rolling_sessions"):
        raise ValueError("capacity.window_kind is unsupported")
    values = _CapacityPolicySettings(
        measure=cast(CapacityMeasure, measure),
        unit=unit,
        capacity_basis=cast(CapacityBasis, basis),
        usage_scope=cast(CapacityUsageScope, usage_scope),
        usage_date_basis=cast(CapacityUsageDateBasis, date_basis),
        max_participation=participation,
        capacity_increment=increment,
        window_kind=cast(CapacityWindowKind, window_kind),
        window_sessions=sessions,
        allowed_observation_precisions=precision_values,
        date_precision_purposes=date_purposes,
        allowed_source_restrictions=restrictions,
    )
    normalized: dict[str, object] = {
        "measure": measure,
        "unit": unit,
        "basis": basis,
        "usage_scope": usage_scope,
        "date_basis": date_basis,
        "max_participation": _canonical_decimal_text(participation),
        "increment": _canonical_decimal_text(increment),
        "window_kind": window_kind,
        "sessions": sessions,
        "allowed_observation_precisions": sorted(precision.value for precision in precision_values),
        "date_precision_purposes": sorted(date_purposes),
        "allowed_source_restrictions": sorted(restrictions),
    }
    return values, normalized


def _normalized_config(
    *,
    schema_version: str,
    scope: str,
    ledger_money_unit: str,
    account_ids: tuple[int, ...],
    industry: dict[str, object],
    capacity: dict[str, object],
    source_max_timestamp_age_seconds: int,
    source_max_date_age_days: int,
    source_references: tuple[PortfolioRiskSourceReference, ...],
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "scope": scope,
        "ledger_money_unit": ledger_money_unit,
        "account_ids": list(account_ids),
        "industry": industry,
        "capacity": capacity,
        "source_max_timestamp_age_seconds": source_max_timestamp_age_seconds,
        "source_max_date_age_days": source_max_date_age_days,
        "source_references": [
            {
                "kind": item.kind,
                "asset_code": item.asset_code,
                "security_id": item.security_id,
                "raw_payload_hash": item.raw_payload_hash,
                "source_record_id": item.source_record_id,
            }
            for item in source_references
        ],
    }


def _canonical_sha256(value: Mapping[str, object]) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _decimal_text(value: object, field_name: str) -> Decimal:
    if type(value) is not str or not value or len(value) > 128:
        raise ValueError(f"{field_name} must be exact decimal text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be exact decimal text") from exc
    exponent = parsed.as_tuple().exponent
    if not parsed.is_finite() or type(exponent) is not int or abs(exponent) > 128:
        raise ValueError(f"{field_name} must be a bounded finite decimal")
    return parsed


def _canonical_decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    decimal_tuple = value.as_tuple()
    digits = list(decimal_tuple.digits)
    raw_exponent = decimal_tuple.exponent
    if type(raw_exponent) is not int:
        raise ValueError("decimal value must be finite")
    exponent = raw_exponent
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in digits)
    if exponent >= 0:
        result = coefficient + ("0" * exponent)
    else:
        split = len(coefficient) + exponent
        result = (
            coefficient[:split] + "." + coefficient[split:]
            if split > 0
            else "0." + ("0" * -split) + coefficient
        )
    return ("-" if decimal_tuple.sign else "") + result


def _precision_tuple(value: object) -> tuple[SourceObservationPrecision, ...]:
    tokens = _token_tuple(value, "allowed_observation_precisions")
    try:
        precisions = tuple(SourceObservationPrecision(token) for token in tokens)
    except ValueError as exc:
        raise ValueError("allowed_observation_precisions contains an unsupported token") from exc
    if len(set(precisions)) != len(precisions):
        raise ValueError("allowed_observation_precisions cannot contain duplicates")
    return precisions


def _token_tuple(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if type(value) is not list:
        raise TypeError(f"{field_name} must be a JSON string array")
    tokens = tuple(_required_token(item, field_name) for item in value)
    if not allow_empty and not tokens:
        raise ValueError(f"{field_name} cannot be empty")
    if len(set(tokens)) != len(tokens):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return tokens


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a JSON object")
    if any(type(key) is not str for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return value


def _require_exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    field_name: str,
) -> None:
    if set(value) != expected:
        raise ValueError(f"{field_name} fields do not match the strict schema")


def _required_token(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a nonempty canonical token")
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")
    return value


def _required_string(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a nonempty canonical string")
    return value


def _positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field_name} must be a positive exact integer")
    return value


def _nonnegative_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a nonnegative exact integer")
    return value


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


def _is_aware(value: datetime) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


__all__ = (
    "SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY",
    "SIMULATED_PORTFOLIO_RISK_SCHEMA",
    "SIMULATED_PORTFOLIO_RISK_SCOPE",
    "PortfolioRiskPolicyBundle",
    "PortfolioRiskPolicyConfigurationError",
    "PortfolioRiskPolicyReadResult",
    "PortfolioRiskPolicyReader",
    "PortfolioRiskSourceReference",
    "parse_portfolio_risk_policy_bundle",
)
