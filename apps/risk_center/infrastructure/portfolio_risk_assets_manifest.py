"""Decode exact retained risk-input manifests into source-qualified domain facts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal, TypeAlias, cast

from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetsReadRequest,
)
from apps.risk_center.application.portfolio_risk_policy import (
    PortfolioRiskPolicyBundle,
    PortfolioRiskSourceReference,
)
from apps.risk_center.domain.portfolio_capacity import (
    CapacityMeasure,
    CapacityValue,
    CapacityWindowObservation,
)
from apps.risk_center.domain.portfolio_exposure_types import (
    EffectiveEndState,
    ETFConstituent,
    ETFConstituentKind,
    ETFConstituentReport,
    IndustryMembership,
    PortfolioAssetKind,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)

_DATASET_KEY = "risk_center.simulated_portfolio_risk_input"
_PARSER_VERSION = "ash07.retained_risk_input.v1"
_MANIFEST_SCHEMA = "ash07.retained_risk_input.v1"
_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "kind",
        "asset_code",
        "security_id",
        "source_record_id",
        "original_body_base64",
        "original_url",
        "source_evidence",
        "facts",
    }
)
_VALUATION_KEYS: frozenset[str] = frozenset({"price", "asset_kind", "quantity_unit", "price_unit"})
_INDUSTRY_KEYS: frozenset[str] = frozenset(
    {
        "taxonomy_id",
        "taxonomy_kind",
        "provider_id",
        "provider_version",
        "industry_code",
        "effective_from",
        "effective_end_state",
        "effective_until",
    }
)
_ETF_REPORT_KEYS: frozenset[str] = frozenset({"report_date", "constituents"})
_ETF_CONSTITUENT_KEYS: frozenset[str] = frozenset({"asset_code", "weight_fraction", "kind"})
_CAPACITY_KEYS: frozenset[str] = frozenset(
    {"window_kind", "start", "end", "sessions", "volume", "amount"}
)
_CAPACITY_VALUE_KEYS: frozenset[str] = frozenset({"value", "unit"})
_SESSION_STATE_KEYS: frozenset[str] = frozenset({"session_date", "suspended"})
_SourceKind: TypeAlias = Literal[
    "valuation",
    "industry_membership",
    "etf_report",
    "capacity_window",
    "execution_session_state",
]
_ReferenceKey: TypeAlias = tuple[str, str, str]
_AssetKey: TypeAlias = tuple[str, str]


@dataclass(frozen=True, slots=True)
class _ValuationFacts:
    price: Decimal | None
    asset_kind: PortfolioAssetKind | None
    quantity_unit: str | None
    price_unit: str | None


@dataclass(frozen=True, slots=True)
class _IndustryMembershipFacts:
    taxonomy_id: str
    taxonomy_kind: str
    provider_id: str
    provider_version: str
    industry_code: str
    effective_from: date | None
    effective_end_state: EffectiveEndState
    effective_until: date | None


@dataclass(frozen=True, slots=True)
class _ETFConstituentFacts:
    asset_code: str
    weight_fraction: Decimal
    kind: ETFConstituentKind


@dataclass(frozen=True, slots=True)
class _ETFReportFacts:
    report_date: date
    constituents: tuple[_ETFConstituentFacts, ...]


@dataclass(frozen=True, slots=True)
class _CapacityValueFacts:
    value: Decimal | None
    unit: str | None


@dataclass(frozen=True, slots=True)
class _CapacityWindowFacts:
    window_kind: Literal["session_cumulative", "rolling_sessions"]
    start: date
    end: date
    sessions: int
    volume: _CapacityValueFacts
    amount: _CapacityValueFacts


@dataclass(frozen=True, slots=True)
class _ExecutionSessionStateFacts:
    session_date: date | None
    suspended: bool | None


_PortfolioRiskFacts: TypeAlias = (
    _ValuationFacts
    | _IndustryMembershipFacts
    | _ETFReportFacts
    | _CapacityWindowFacts
    | _ExecutionSessionStateFacts
)


@dataclass(frozen=True, slots=True)
class _LoadedSource:
    reference: PortfolioRiskSourceReference
    evidence: PortfolioRiskSourceEvidence
    original_url: str | None
    facts: _PortfolioRiskFacts | None


@dataclass(frozen=True, slots=True)
class _SourceRead:
    source: _LoadedSource | None
    reason_codes: tuple[str, ...]
    blocked: bool
    partial: bool


_SOURCE_KIND_VALUES: frozenset[str] = frozenset(
    {
        "valuation",
        "industry_membership",
        "etf_report",
        "capacity_window",
        "execution_session_state",
    }
)


def _parse_facts(kind: _SourceKind, raw: object) -> _PortfolioRiskFacts:
    facts = _require_mapping(raw, "facts")
    if kind == "valuation":
        _require_exact_keys(facts, _VALUATION_KEYS, "valuation facts")
        asset_kind_text = _optional_string(facts["asset_kind"], "asset_kind")
        asset_kind: PortfolioAssetKind | None = None
        if asset_kind_text is not None:
            asset_kind = PortfolioAssetKind(asset_kind_text)
        price = _decimal_text_or_none(facts["price"], "price")
        if price is not None and price < 0:
            raise ValueError("price cannot be negative")
        return _ValuationFacts(
            price=price,
            asset_kind=asset_kind,
            quantity_unit=_optional_token(facts["quantity_unit"], "quantity_unit"),
            price_unit=_optional_token(facts["price_unit"], "price_unit"),
        )
    if kind == "industry_membership":
        _require_exact_keys(facts, _INDUSTRY_KEYS, "industry membership facts")
        end_state_text = _required_token(facts["effective_end_state"], "effective_end_state")
        return _IndustryMembershipFacts(
            taxonomy_id=_required_token(facts["taxonomy_id"], "taxonomy_id"),
            taxonomy_kind=_required_token(facts["taxonomy_kind"], "taxonomy_kind"),
            provider_id=_required_token(facts["provider_id"], "provider_id"),
            provider_version=_required_token(facts["provider_version"], "provider_version"),
            industry_code=_required_token(facts["industry_code"], "industry_code"),
            effective_from=_iso_date_or_none(facts["effective_from"], "effective_from"),
            effective_end_state=EffectiveEndState(end_state_text),
            effective_until=_iso_date_or_none(facts["effective_until"], "effective_until"),
        )
    if kind == "etf_report":
        _require_exact_keys(facts, _ETF_REPORT_KEYS, "ETF report facts")
        report_date = _iso_date(facts["report_date"], "report_date")
        raw_constituents = facts["constituents"]
        if type(raw_constituents) is not list:
            raise TypeError("constituents must be a JSON array")
        constituents: list[_ETFConstituentFacts] = []
        for row in raw_constituents:
            constituent = _require_mapping(row, "ETF constituent")
            _require_exact_keys(constituent, _ETF_CONSTITUENT_KEYS, "ETF constituent")
            kind_text = _required_token(constituent["kind"], "constituent.kind")
            weight_fraction = _decimal_text(
                constituent["weight_fraction"],
                "weight_fraction",
            )
            if weight_fraction < 0 or weight_fraction > 1:
                raise ValueError("weight_fraction must be in [0, 1]")
            constituents.append(
                _ETFConstituentFacts(
                    asset_code=_required_token(constituent["asset_code"], "asset_code"),
                    weight_fraction=weight_fraction,
                    kind=ETFConstituentKind(kind_text),
                )
            )
        return _ETFReportFacts(report_date=report_date, constituents=tuple(constituents))
    if kind == "capacity_window":
        _require_exact_keys(facts, _CAPACITY_KEYS, "capacity window facts")
        window_kind_text = _required_token(facts["window_kind"], "window_kind")
        if window_kind_text not in ("session_cumulative", "rolling_sessions"):
            raise ValueError("window_kind is unsupported")
        sessions = _positive_integer(facts["sessions"], "sessions")
        return _CapacityWindowFacts(
            window_kind=cast(Literal["session_cumulative", "rolling_sessions"], window_kind_text),
            start=_iso_date(facts["start"], "start"),
            end=_iso_date(facts["end"], "end"),
            sessions=sessions,
            volume=_parse_capacity_value(facts["volume"], "volume"),
            amount=_parse_capacity_value(facts["amount"], "amount"),
        )
    _require_exact_keys(facts, _SESSION_STATE_KEYS, "execution session state facts")
    suspended = facts["suspended"]
    if suspended is not None and type(suspended) is not bool:
        raise TypeError("suspended must be a boolean or None")
    return _ExecutionSessionStateFacts(
        session_date=_iso_date_or_none(facts["session_date"], "session_date"),
        suspended=suspended,
    )


def _membership_from_source(
    source: _LoadedSource | None,
    reasons: list[str],
) -> IndustryMembership | None:
    if source is None or not isinstance(source.facts, _IndustryMembershipFacts):
        return None
    facts = source.facts
    if facts.effective_from is None:
        reasons.append("RISK_INPUT_INDUSTRY_EFFECTIVE_FROM_UNKNOWN")
        return None
    if facts.effective_end_state is EffectiveEndState.BOUNDED and facts.effective_until is None:
        reasons.append("RISK_INPUT_INDUSTRY_EFFECTIVE_UNTIL_UNKNOWN")
        return None
    if (
        facts.effective_end_state is not EffectiveEndState.BOUNDED
        and facts.effective_until is not None
    ):
        reasons.append("RISK_INPUT_INDUSTRY_EFFECTIVE_END_CONFLICT")
        return None
    try:
        membership = IndustryMembership(
            taxonomy_id=facts.taxonomy_id,
            taxonomy_kind=facts.taxonomy_kind,
            provider_id=facts.provider_id,
            provider_version=facts.provider_version,
            industry_code=facts.industry_code,
            effective_from=facts.effective_from,
            effective_end_state=facts.effective_end_state,
            source_evidence=source.evidence,
            effective_until=facts.effective_until,
        )
    except (TypeError, ValueError):
        reasons.append("RISK_INPUT_INDUSTRY_MEMBERSHIP_FACTS_INVALID")
        return None
    if facts.effective_end_state is EffectiveEndState.UNKNOWN:
        reasons.append("RISK_INPUT_INDUSTRY_EFFECTIVE_END_UNKNOWN")
    return membership


def _etf_report_from_source(
    *,
    source: _LoadedSource,
    facts: _ETFReportFacts,
    references: tuple[PortfolioRiskSourceReference, ...],
    memberships: Mapping[_AssetKey, IndustryMembership | None],
) -> tuple[ETFConstituentReport | None, tuple[str, ...], bool]:
    reasons: list[str] = []
    constituents: list[ETFConstituent] = []
    blocked = False
    for item in facts.constituents:
        membership: IndustryMembership | None = None
        if item.kind is ETFConstituentKind.EQUITY:
            matches = tuple(
                ref
                for ref in references
                if ref.kind == "industry_membership" and ref.asset_code == item.asset_code
            )
            if len(matches) == 0:
                reasons.append("RISK_INPUT_ETF_CONSTITUENT_INDUSTRY_REFERENCE_MISSING")
            elif len(matches) > 1:
                reasons.append("RISK_INPUT_ETF_CONSTITUENT_INDUSTRY_REFERENCE_AMBIGUOUS")
                blocked = True
            else:
                membership = memberships.get((matches[0].asset_code, matches[0].security_id))
                if membership is None:
                    reasons.append("RISK_INPUT_ETF_CONSTITUENT_INDUSTRY_UNKNOWN")
        constituents.append(
            ETFConstituent(
                asset_code=item.asset_code,
                weight_fraction=item.weight_fraction,
                kind=item.kind,
                industry_membership=membership,
            )
        )
    try:
        report = ETFConstituentReport(
            report_date=facts.report_date,
            source_evidence=source.evidence,
            constituents=tuple(constituents),
        )
    except (TypeError, ValueError):
        return None, ("RISK_INPUT_ETF_REPORT_FACTS_INVALID",), True
    return report, tuple(dict.fromkeys(reasons)), blocked


def _capacity_observation_from_sources(
    *,
    asset_code: str,
    security_id: str,
    facts: _CapacityWindowFacts,
    window_source: _LoadedSource,
    state_source: _LoadedSource | None,
    state_facts: _ExecutionSessionStateFacts | None,
    request: PortfolioRiskAssetsReadRequest,
    quantity_unit: str | None,
    ledger_money_unit: str,
    capacity_measure: CapacityMeasure,
    capacity_unit: str,
) -> tuple[CapacityWindowObservation | None, tuple[str, ...], bool]:
    reasons: list[str] = []
    volume = _capacity_value_from_facts(facts.volume, "volume", reasons)
    amount = _capacity_value_from_facts(facts.amount, "amount", reasons)
    unit_blocked = False
    if facts.volume.value is not None and facts.volume.unit is not None:
        if quantity_unit is None:
            reasons.append("RISK_INPUT_CAPACITY_VOLUME_QUANTITY_UNIT_UNKNOWN")
            volume = CapacityValue(value=None, unit=None)
        elif facts.volume.unit != quantity_unit:
            reasons.append("RISK_INPUT_CAPACITY_VOLUME_QUANTITY_UNIT_MISMATCH")
            unit_blocked = True
        if capacity_measure == "volume" and facts.volume.unit != capacity_unit:
            reasons.append("RISK_INPUT_CAPACITY_POLICY_UNIT_MISMATCH")
            unit_blocked = True
    if facts.amount.value is not None and facts.amount.unit is not None:
        if facts.amount.unit != ledger_money_unit:
            reasons.append("RISK_INPUT_CAPACITY_AMOUNT_LEDGER_UNIT_MISMATCH")
            unit_blocked = True
        if capacity_measure == "amount" and facts.amount.unit != capacity_unit:
            reasons.append("RISK_INPUT_CAPACITY_POLICY_UNIT_MISMATCH")
            unit_blocked = True
    if (
        capacity_measure == "volume"
        and quantity_unit is not None
        and (capacity_unit != quantity_unit)
    ):
        reasons.append("RISK_INPUT_CAPACITY_POLICY_UNIT_MISMATCH")
        unit_blocked = True
    if capacity_measure == "amount" and capacity_unit != ledger_money_unit:
        reasons.append("RISK_INPUT_CAPACITY_POLICY_UNIT_MISMATCH")
        unit_blocked = True
    if unit_blocked:
        return None, tuple(dict.fromkeys(reasons)), True
    state_date = state_facts.session_date if state_facts is not None else None
    suspended = state_facts.suspended if state_facts is not None else None
    state_evidence = state_source.evidence if state_source is not None else None
    if state_source is None:
        reasons.append("RISK_INPUT_EXECUTION_SESSION_STATE_REFERENCE_MISSING")
    elif state_facts is None:
        reasons.append("RISK_INPUT_EXECUTION_SESSION_STATE_FACTS_UNKNOWN")
    elif state_date is None:
        reasons.append("RISK_INPUT_EXECUTION_SESSION_DATE_UNKNOWN")
    if state_date is not None and state_date > request.business_date:
        reasons.append("RISK_INPUT_EXECUTION_SESSION_STATE_FUTURE")
        return None, tuple(dict.fromkeys(reasons)), True
    if state_date is not None and state_date != request.execution_session:
        reasons.append("RISK_INPUT_EXECUTION_SESSION_DATE_MISMATCH")
        return None, tuple(dict.fromkeys(reasons)), True
    if state_facts is not None and state_date is not None and state_source is not None:
        if state_source.evidence.effective_on is None:
            reasons.append("RISK_INPUT_EXECUTION_SESSION_EFFECTIVE_DATE_UNKNOWN")
            return None, tuple(dict.fromkeys(reasons)), False
        if state_source.evidence.effective_on != state_date:
            reasons.append("RISK_INPUT_EXECUTION_SESSION_EFFECTIVE_DATE_MISMATCH")
            return None, tuple(dict.fromkeys(reasons)), True
        if state_source.evidence.observation_precision is SourceObservationPrecision.DATE:
            if state_source.evidence.observed_on != state_date:
                reasons.append("RISK_INPUT_EXECUTION_SESSION_OBSERVATION_DATE_MISMATCH")
                return None, tuple(dict.fromkeys(reasons)), True
            if state_source.evidence.decision_date_cutoff != request.business_date:
                reasons.append("RISK_INPUT_EXECUTION_SESSION_DATE_CUTOFF_MISMATCH")
                return None, tuple(dict.fromkeys(reasons)), True
        if state_source.evidence.coverage.status is not CoverageStatus.COMPLETE:
            reasons.append("RISK_INPUT_EXECUTION_SESSION_COVERAGE_INCOMPLETE")
            return None, tuple(dict.fromkeys(reasons)), False
    if state_facts is not None and suspended is None:
        reasons.append("RISK_INPUT_EXECUTION_SESSION_SUSPENSION_UNKNOWN")
        return None, tuple(dict.fromkeys(reasons)), False
    if state_source is None or state_facts is None or state_date is None:
        return None, tuple(dict.fromkeys(reasons)), False
    try:
        observation = CapacityWindowObservation(
            asset_code=asset_code,
            security_id=security_id,
            window_kind=facts.window_kind,
            window_start=facts.start,
            window_end=facts.end,
            window_sessions=facts.sessions,
            volume=volume,
            amount=amount,
            execution_session_suspended=suspended,
            execution_session_state_date=state_date,
            execution_session_state_evidence=state_evidence,
            source_evidence=window_source.evidence,
        )
    except (TypeError, ValueError):
        return None, ("RISK_INPUT_CAPACITY_WINDOW_FACTS_INVALID",), True
    return observation, tuple(dict.fromkeys(reasons)), False


def _capacity_value_from_facts(
    facts: _CapacityValueFacts,
    field_name: str,
    reasons: list[str],
) -> CapacityValue:
    if facts.value is None and facts.unit is None:
        reasons.append(f"RISK_INPUT_CAPACITY_{field_name.upper()}_UNKNOWN")
        return CapacityValue(value=None, unit=None)
    if facts.value is None or facts.unit is None:
        reasons.append(f"RISK_INPUT_CAPACITY_{field_name.upper()}_VALUE_UNIT_INCOMPLETE")
        return CapacityValue(value=None, unit=None)
    return CapacityValue(value=facts.value, unit=facts.unit)


def _policy_source_rules(
    policy: PortfolioRiskPolicyBundle,
    kind: _SourceKind,
    capacity_purpose: str,
) -> tuple[
    str,
    tuple[SourceObservationPrecision, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    if kind in ("valuation", "industry_membership", "etf_report"):
        industry_policy = policy.industry_policy
        return (
            industry_policy.requested_purpose,
            industry_policy.allowed_observation_precisions,
            industry_policy.date_precision_purposes,
            industry_policy.allowed_source_restrictions,
        )
    capacity_policy = policy.capacity_policy
    return (
        capacity_purpose,
        capacity_policy.allowed_observation_precisions,
        capacity_policy.date_precision_purposes,
        capacity_policy.allowed_source_restrictions,
    )


def _source_age_reason(
    evidence: PortfolioRiskSourceEvidence,
    request: PortfolioRiskAssetsReadRequest,
) -> str | None:
    if evidence.observation_precision is SourceObservationPrecision.TIMESTAMP:
        if evidence.observed_at is None:
            return "RISK_INPUT_SOURCE_TIMESTAMP_AGE_UNKNOWN"
        if evidence.observed_at > request.as_of:
            return "RISK_INPUT_SOURCE_TIMESTAMP_AFTER_CUTOFF"
        if (request.as_of - evidence.observed_at) > timedelta(
            seconds=request.policy.source_max_timestamp_age_seconds
        ):
            return "RISK_INPUT_SOURCE_TIMESTAMP_AGE_EXCEEDED"
        return None
    if evidence.observation_precision is SourceObservationPrecision.DATE:
        if evidence.observed_on is None:
            return "RISK_INPUT_SOURCE_DATE_AGE_UNKNOWN"
        if evidence.observed_on > request.business_date:
            return "RISK_INPUT_SOURCE_DATE_AFTER_BUSINESS_DATE"
        age_days = (request.business_date - evidence.observed_on).days
        if age_days > request.policy.source_max_date_age_days:
            return "RISK_INPUT_SOURCE_DATE_AGE_EXCEEDED"
        return None
    return "RISK_INPUT_SOURCE_AGE_UNKNOWN"


def _parse_capacity_value(raw: object, field_name: str) -> _CapacityValueFacts:
    value = _require_mapping(raw, field_name)
    _require_exact_keys(value, _CAPACITY_VALUE_KEYS, field_name)
    parsed_value = _decimal_text_or_none(value["value"], f"{field_name}.value")
    if parsed_value is not None and parsed_value < 0:
        raise ValueError(f"{field_name}.value cannot be negative")
    unit = _optional_token(value["unit"], f"{field_name}.unit")
    return _CapacityValueFacts(
        value=parsed_value,
        unit=unit,
    )


def _validate_json_source_clock_types(raw: Mapping[str, object]) -> None:
    for field_name in ("observed_at", "available_at", "known_at", "valid_until"):
        value = raw.get(field_name)
        if value is not None and type(value) is not str:
            raise TypeError(f"source_evidence.{field_name} must be an ISO datetime string")
    for field_name in ("observed_on", "effective_on", "effective_until"):
        value = raw.get(field_name)
        if value is not None and type(value) is not str:
            raise TypeError(f"source_evidence.{field_name} must be an ISO date string")


def _decode_original_body(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("original_body_base64 must be strict base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("original_body_base64 must use canonical base64 encoding")
    return decoded


def _manifest_payload_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a JSON object")
    if any(type(key) is not str for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return cast(Mapping[str, object], value)


def _require_exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    field_name: str,
) -> None:
    if set(value) != expected:
        raise ValueError(f"{field_name} fields do not match the retained input schema")


def _required_token(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a canonical nonempty token")
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")
    return value


def _required_string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value.strip() != value:
        raise ValueError(f"{field_name} must be canonical")
    return value


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field_name)


def _optional_token(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_token(value, field_name)


def _iso_date(value: object, field_name: str) -> date:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an ISO date string")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use YYYY-MM-DD form")
    return parsed


def _iso_date_or_none(value: object, field_name: str) -> date | None:
    if value is None:
        return None
    return _iso_date(value, field_name)


def _decimal_text(value: object, field_name: str) -> Decimal:
    if type(value) is not str or not value or len(value) > 128:
        raise TypeError(f"{field_name} must be exact decimal text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be exact decimal text") from exc
    exponent = parsed.as_tuple().exponent
    if not parsed.is_finite() or type(exponent) is not int or abs(exponent) > 128:
        raise ValueError(f"{field_name} must be a bounded finite decimal")
    return parsed


def _decimal_text_or_none(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal_text(value, field_name)


def _positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field_name} must be a positive exact integer")
    return value
