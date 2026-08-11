"""Pure owner-definition contracts for canonical R4 monitoring registries."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, StrEnum

from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringPeriodCalendar,
    R4MonitoringPeriodEntry,
    R4MonitoringPolicy,
    R4MonitoringThreshold,
)


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


def _canonical(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return "0" if normalized == 0 else format(normalized, "f")
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise TypeError(f"unsupported canonical R4 owner value: {type(value).__name__}")


def _definition_hash(
    schema: str,
    value: R4MonitoringPolicyDefinition | R4MonitoringCalendarDefinition,
) -> str:
    payload = {
        "schema": schema,
        "definition": {
            item.name: _canonical(getattr(value, item.name))
            for item in fields(value)
            if item.name != "content_hash"
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class R4MonitoringOwnerRecordKind(StrEnum):
    """Research-owned monitoring registry record kind."""

    POLICY = "policy"
    CALENDAR = "calendar"


@dataclass(frozen=True)
class R4MonitoringPolicyDefinition:
    """Trusted policy semantics before the Research server claims recorded_at."""

    policy_id: str
    policy_version: str
    active_decision: R4PromotionDecisionIdentity
    thresholds: tuple[R4MonitoringThreshold, ...]
    minimum_observation_count: int
    maximum_observation_age_seconds: int
    expected_source_owner: str
    expected_pit_manifest_id: str
    expected_pit_manifest_hash: str
    expected_label_protocol_version: str
    expected_label_set_hash: str
    expected_data_schema_hash: str
    expected_period_calendar_owner: str
    expected_period_calendar_id: str
    expected_period_calendar_version: str
    expected_period_calendar_hash: str
    expected_evidence_ref_prefix: str
    active_from: datetime
    active_until: datetime
    content_hash: str = field(init=False)

    @classmethod
    def from_policy(cls, policy: R4MonitoringPolicy) -> R4MonitoringPolicyDefinition:
        """Strip the owner server clock from one fully validated test/source value."""

        if type(policy) is not R4MonitoringPolicy:
            raise ValueError("policy must be the exact R4MonitoringPolicy type")
        policy.validated_copy()
        return cls(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            active_decision=policy.active_decision,
            thresholds=policy.thresholds,
            minimum_observation_count=policy.minimum_observation_count,
            maximum_observation_age_seconds=policy.maximum_observation_age_seconds,
            expected_source_owner=policy.expected_source_owner,
            expected_pit_manifest_id=policy.expected_pit_manifest_id,
            expected_pit_manifest_hash=policy.expected_pit_manifest_hash,
            expected_label_protocol_version=policy.expected_label_protocol_version,
            expected_label_set_hash=policy.expected_label_set_hash,
            expected_data_schema_hash=policy.expected_data_schema_hash,
            expected_period_calendar_owner=policy.expected_period_calendar_owner,
            expected_period_calendar_id=policy.expected_period_calendar_id,
            expected_period_calendar_version=policy.expected_period_calendar_version,
            expected_period_calendar_hash=policy.expected_period_calendar_hash,
            expected_evidence_ref_prefix=policy.expected_evidence_ref_prefix,
            active_from=policy.active_from,
            active_until=policy.active_until,
        )

    def __post_init__(self) -> None:
        self.build(recorded_at=self.active_from)
        object.__setattr__(
            self,
            "content_hash",
            _definition_hash("research-r4-monitoring-policy-definition.v1", self),
        )

    def build(self, *, recorded_at: datetime) -> R4MonitoringPolicy:
        """Build the final canonical policy using only the server-owned clock."""

        return R4MonitoringPolicy(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            active_decision=self.active_decision,
            thresholds=self.thresholds,
            minimum_observation_count=self.minimum_observation_count,
            maximum_observation_age_seconds=self.maximum_observation_age_seconds,
            expected_source_owner=self.expected_source_owner,
            expected_pit_manifest_id=self.expected_pit_manifest_id,
            expected_pit_manifest_hash=self.expected_pit_manifest_hash,
            expected_label_protocol_version=self.expected_label_protocol_version,
            expected_label_set_hash=self.expected_label_set_hash,
            expected_data_schema_hash=self.expected_data_schema_hash,
            expected_period_calendar_owner=self.expected_period_calendar_owner,
            expected_period_calendar_id=self.expected_period_calendar_id,
            expected_period_calendar_version=self.expected_period_calendar_version,
            expected_period_calendar_hash=self.expected_period_calendar_hash,
            expected_evidence_ref_prefix=self.expected_evidence_ref_prefix,
            recorded_at=recorded_at,
            active_from=self.active_from,
            active_until=self.active_until,
        )


@dataclass(frozen=True)
class R4MonitoringCalendarDefinition:
    """Trusted calendar semantics before the Research server claims recorded_at."""

    source_owner: str
    calendar_id: str
    calendar_version: str
    valid_from: datetime
    valid_until: datetime
    entries: tuple[R4MonitoringPeriodEntry, ...]
    content_hash: str = field(init=False)

    @classmethod
    def from_calendar(cls, calendar: R4MonitoringPeriodCalendar) -> R4MonitoringCalendarDefinition:
        """Strip the owner server clock from one validated calendar."""

        if type(calendar) is not R4MonitoringPeriodCalendar:
            raise ValueError("calendar must be the exact R4MonitoringPeriodCalendar type")
        R4MonitoringPeriodCalendar.__post_init__(calendar)
        return cls(
            source_owner=calendar.source_owner,
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            valid_from=calendar.valid_from,
            valid_until=calendar.valid_until,
            entries=calendar.entries,
        )

    def __post_init__(self) -> None:
        self.build(recorded_at=self.valid_from)
        object.__setattr__(
            self,
            "content_hash",
            _definition_hash("research-r4-monitoring-calendar-definition.v1", self),
        )

    def build(self, *, recorded_at: datetime) -> R4MonitoringPeriodCalendar:
        """Build the final canonical calendar using only the server-owned clock."""

        return R4MonitoringPeriodCalendar(
            source_owner=self.source_owner,
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            recorded_at=recorded_at,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            entries=self.entries,
        )


@dataclass(frozen=True)
class R4MonitoringOwnerSourceReceipt:
    """Exact Research owner receipt binding one definition to an active interval."""

    record_kind: R4MonitoringOwnerRecordKind
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
        record_kind: R4MonitoringOwnerRecordKind,
        source_owner: str,
        source_receipt_id: str,
        source_receipt_version: str,
        definition_hash: str,
        available_at: datetime,
        valid_until: datetime,
    ) -> R4MonitoringOwnerSourceReceipt:
        """Create a canonical source receipt without any default evidence."""

        digest = _source_receipt_hash(
            record_kind=record_kind,
            source_owner=source_owner,
            source_receipt_id=source_receipt_id,
            source_receipt_version=source_receipt_version,
            definition_hash=definition_hash,
            available_at=available_at,
            valid_until=valid_until,
        )
        return cls(
            record_kind=record_kind,
            source_owner=source_owner,
            source_receipt_id=source_receipt_id,
            source_receipt_version=source_receipt_version,
            definition_hash=definition_hash,
            available_at=available_at,
            valid_until=valid_until,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.record_kind, R4MonitoringOwnerRecordKind):
            raise ValueError("record_kind is invalid")
        if self.source_owner != "research":
            raise ValueError("R4 monitoring policy/calendar receipts must be Research-owned")
        for name in ("source_owner", "source_receipt_id", "source_receipt_version"):
            _require_token(getattr(self, name), name)
        _require_hash(self.definition_hash, "definition_hash")
        _require_hash(self.content_hash, "content_hash")
        _require_aware(self.available_at, "available_at")
        _require_aware(self.valid_until, "valid_until")
        if self.available_at >= self.valid_until:
            raise ValueError("source receipt validity is empty")
        expected = _source_receipt_hash(
            record_kind=self.record_kind,
            source_owner=self.source_owner,
            source_receipt_id=self.source_receipt_id,
            source_receipt_version=self.source_receipt_version,
            definition_hash=self.definition_hash,
            available_at=self.available_at,
            valid_until=self.valid_until,
        )
        if self.content_hash.lower() != expected:
            raise ValueError("source receipt content_hash mismatch")


def _source_receipt_hash(
    *,
    record_kind: R4MonitoringOwnerRecordKind,
    source_owner: str,
    source_receipt_id: str,
    source_receipt_version: str,
    definition_hash: str,
    available_at: datetime,
    valid_until: datetime,
) -> str:
    payload = {
        "schema": "research-r4-monitoring-owner-source-receipt.v1",
        "record_kind": record_kind.value,
        "source_owner": source_owner,
        "source_receipt_id": source_receipt_id,
        "source_receipt_version": source_receipt_version,
        "definition_hash": definition_hash.lower(),
        "available_at": _canonical(available_at),
        "valid_until": _canonical(valid_until),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "R4MonitoringCalendarDefinition",
    "R4MonitoringOwnerRecordKind",
    "R4MonitoringOwnerSourceReceipt",
    "R4MonitoringPolicyDefinition",
]
