"""Pure Portfolio owner contracts for R4 monitoring raw-fact receipts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import Decimal


def _require_token(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{field_name} must be a SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _decimal_text(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("raw metric value must be a finite Decimal")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PortfolioR4MonitoringRawMetric:
    """One owner-neutral named metric without Research policy interpretation."""

    metric_key: str
    unit: str
    value: Decimal

    def __post_init__(self) -> None:
        _require_token(self.metric_key, "metric_key")
        _require_token(self.unit, "unit")
        _decimal_text(self.value)


@dataclass(frozen=True)
class PortfolioR4MonitoringRawFactReceipt:
    """One immutable Portfolio-owned raw-fact owner receipt."""

    observation_id: str
    observation_version: str
    period_id: str
    calendar_id: str
    calendar_version: str
    calendar_hash: str
    period_start: datetime
    period_end: datetime
    active_decision_id: str
    active_decision_version: str
    active_decision_hash: str
    policy_id: str
    policy_version: str
    policy_hash: str
    portfolio_record_id: str
    portfolio_record_hash: str
    portfolio_record_content_hash: str
    r3_attestation_content_hash: str
    observed_at: datetime
    available_at: datetime
    owner_recorded_at: datetime
    valid_until: datetime
    pit_manifest_id: str
    pit_manifest_hash: str
    evidence_ref: str
    label_protocol_version: str
    observed_label_set_hash: str
    observed_data_schema_hash: str
    metrics: tuple[PortfolioR4MonitoringRawMetric, ...]
    owner: str = "portfolio"
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_publish_current: bool = True
    must_not_execute: bool = True
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_raw_fields(self)
        object.__setattr__(self, "content_hash", _raw_fact_hash(self))


@dataclass(frozen=True)
class R4MonitoringRawFactDefinition:
    """Canonical raw metrics before Portfolio claims owner_recorded_at."""

    observation_id: str
    observation_version: str
    period_id: str
    calendar_id: str
    calendar_version: str
    calendar_hash: str
    period_start: datetime
    period_end: datetime
    active_decision_id: str
    active_decision_version: str
    active_decision_hash: str
    policy_id: str
    policy_version: str
    policy_hash: str
    portfolio_record_id: str
    portfolio_record_hash: str
    portfolio_record_content_hash: str
    r3_attestation_content_hash: str
    observed_at: datetime
    available_at: datetime
    valid_until: datetime
    pit_manifest_id: str
    pit_manifest_hash: str
    evidence_ref: str
    label_protocol_version: str
    observed_label_set_hash: str
    observed_data_schema_hash: str
    metrics: tuple[PortfolioR4MonitoringRawMetric, ...]
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        self.build(owner_recorded_at=self.available_at)
        payload: dict[str, object] = {
            "schema": "portfolio-r4-monitoring-raw-fact-definition.v1",
            "fields": {
                item.name: _definition_value(getattr(self, item.name))
                for item in fields(self)
                if item.name != "content_hash"
            },
        }
        object.__setattr__(self, "content_hash", _hash(payload))

    def build(self, *, owner_recorded_at: datetime) -> PortfolioR4MonitoringRawFactReceipt:
        """Build the owner receipt using only Portfolio's server clock."""

        return PortfolioR4MonitoringRawFactReceipt(
            observation_id=self.observation_id,
            observation_version=self.observation_version,
            period_id=self.period_id,
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            calendar_hash=self.calendar_hash,
            period_start=self.period_start,
            period_end=self.period_end,
            active_decision_id=self.active_decision_id,
            active_decision_version=self.active_decision_version,
            active_decision_hash=self.active_decision_hash,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            policy_hash=self.policy_hash,
            portfolio_record_id=self.portfolio_record_id,
            portfolio_record_hash=self.portfolio_record_hash,
            portfolio_record_content_hash=self.portfolio_record_content_hash,
            r3_attestation_content_hash=self.r3_attestation_content_hash,
            observed_at=self.observed_at,
            available_at=self.available_at,
            owner_recorded_at=owner_recorded_at,
            valid_until=self.valid_until,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_hash=self.pit_manifest_hash,
            evidence_ref=self.evidence_ref,
            label_protocol_version=self.label_protocol_version,
            observed_label_set_hash=self.observed_label_set_hash,
            observed_data_schema_hash=self.observed_data_schema_hash,
            metrics=self.metrics,
        )


@dataclass(frozen=True)
class PortfolioR4MonitoringRawFactSourceReceipt:
    """Portfolio source receipt binding a raw definition to availability."""

    source_owner: str
    source_receipt_id: str
    source_receipt_version: str
    definition_hash: str
    available_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        source_receipt_id: str,
        source_receipt_version: str,
        definition_hash: str,
        available_at: datetime,
        valid_until: datetime,
    ) -> PortfolioR4MonitoringRawFactSourceReceipt:
        """Create one content-addressed Portfolio source receipt."""

        payload = _source_payload(
            source_receipt_id=source_receipt_id,
            source_receipt_version=source_receipt_version,
            definition_hash=definition_hash,
            available_at=available_at,
            valid_until=valid_until,
        )
        return cls(
            source_owner="portfolio",
            source_receipt_id=source_receipt_id,
            source_receipt_version=source_receipt_version,
            definition_hash=definition_hash,
            available_at=available_at,
            valid_until=valid_until,
            content_hash=_hash(payload),
        )

    def __post_init__(self) -> None:
        if self.source_owner != "portfolio":
            raise ValueError("R4 monitoring raw facts must remain Portfolio-owned")
        for name in ("source_owner", "source_receipt_id", "source_receipt_version"):
            _require_token(getattr(self, name), name)
        _require_hash(self.definition_hash, "definition_hash")
        _require_hash(self.content_hash, "content_hash")
        _require_aware(self.available_at, "available_at")
        _require_aware(self.valid_until, "valid_until")
        if self.available_at >= self.valid_until:
            raise ValueError("raw-fact source receipt validity is empty")
        expected = _hash(
            _source_payload(
                source_receipt_id=self.source_receipt_id,
                source_receipt_version=self.source_receipt_version,
                definition_hash=self.definition_hash,
                available_at=self.available_at,
                valid_until=self.valid_until,
            )
        )
        if self.content_hash.lower() != expected:
            raise ValueError("raw-fact source receipt hash mismatch")


def _validate_raw_fields(value: PortfolioR4MonitoringRawFactReceipt) -> None:
    for name in (
        "observation_id",
        "observation_version",
        "calendar_id",
        "calendar_version",
        "active_decision_id",
        "active_decision_version",
        "policy_id",
        "policy_version",
        "portfolio_record_id",
        "pit_manifest_id",
        "label_protocol_version",
    ):
        _require_token(getattr(value, name), name)
    for name in (
        "period_id",
        "calendar_hash",
        "active_decision_hash",
        "policy_hash",
        "portfolio_record_hash",
        "portfolio_record_content_hash",
        "r3_attestation_content_hash",
        "pit_manifest_hash",
        "observed_label_set_hash",
        "observed_data_schema_hash",
    ):
        _require_hash(getattr(value, name), name)
    for name in (
        "period_start",
        "period_end",
        "observed_at",
        "available_at",
        "owner_recorded_at",
        "valid_until",
    ):
        _require_aware(getattr(value, name), name)
    if not (
        value.period_start
        < value.period_end
        <= value.observed_at
        <= value.available_at
        <= value.owner_recorded_at
        < value.valid_until
    ):
        raise ValueError("Portfolio R4 raw-fact clocks are invalid")
    if value.owner != "portfolio" or not value.metrics:
        raise ValueError("Portfolio R4 raw-fact owner/metrics are invalid")
    if any(type(item) is not PortfolioR4MonitoringRawMetric for item in value.metrics):
        raise ValueError("Portfolio R4 raw metrics must use exact types")
    keys = tuple(item.metric_key for item in value.metrics)
    if len(keys) != len(set(keys)):
        raise ValueError("Portfolio R4 raw metric keys must be unique")
    if not (
        value.research_only
        and value.must_not_use_for_decision
        and value.must_not_publish_current
        and value.must_not_execute
    ):
        raise ValueError("Portfolio R4 raw facts cannot authorize production behavior")


def _raw_fact_hash(value: PortfolioR4MonitoringRawFactReceipt) -> str:
    payload: dict[str, object] = {
        "schema": "portfolio-r4-monitoring-raw-fact-receipt.v1",
        "identity": [value.observation_id, value.observation_version],
        "period": [
            value.period_id.lower(),
            value.calendar_id,
            value.calendar_version,
            value.calendar_hash.lower(),
            _utc_text(value.period_start),
            _utc_text(value.period_end),
        ],
        "decision": [
            value.active_decision_id,
            value.active_decision_version,
            value.active_decision_hash.lower(),
        ],
        "policy": [value.policy_id, value.policy_version, value.policy_hash.lower()],
        "portfolio": [
            value.portfolio_record_id,
            value.portfolio_record_hash.lower(),
            value.portfolio_record_content_hash.lower(),
        ],
        "r3": value.r3_attestation_content_hash.lower(),
        "clocks": [
            _utc_text(value.observed_at),
            _utc_text(value.available_at),
            _utc_text(value.owner_recorded_at),
            _utc_text(value.valid_until),
        ],
        "pit": [value.pit_manifest_id, value.pit_manifest_hash.lower()],
        "evidence_ref": value.evidence_ref,
        "labels": [value.label_protocol_version, value.observed_label_set_hash.lower()],
        "schema_hash": value.observed_data_schema_hash.lower(),
        "metrics": [
            [item.metric_key, item.unit, _decimal_text(item.value)]
            for item in sorted(value.metrics, key=lambda metric: metric.metric_key)
        ],
        "safety": [True, True, True, True],
    }
    return _hash(payload)


def _definition_value(value: object) -> object:
    if isinstance(value, datetime):
        return _utc_text(value)
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, PortfolioR4MonitoringRawMetric):
        return [value.metric_key, value.unit, _decimal_text(value.value)]
    if isinstance(value, tuple):
        return [_definition_value(item) for item in value]
    if isinstance(value, str):
        return value
    raise TypeError(f"unsupported raw definition value: {type(value).__name__}")


def _source_payload(
    *,
    source_receipt_id: str,
    source_receipt_version: str,
    definition_hash: str,
    available_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "portfolio-r4-monitoring-raw-fact-source-receipt.v1",
        "source_owner": "portfolio",
        "source_receipt_id": source_receipt_id,
        "source_receipt_version": source_receipt_version,
        "definition_hash": definition_hash.lower(),
        "available_at": _utc_text(available_at),
        "valid_until": _utc_text(valid_until),
    }


__all__ = [
    "PortfolioR4MonitoringRawFactReceipt",
    "PortfolioR4MonitoringRawFactSourceReceipt",
    "PortfolioR4MonitoringRawMetric",
    "R4MonitoringRawFactDefinition",
]
