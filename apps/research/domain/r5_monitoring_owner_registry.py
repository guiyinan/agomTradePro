"""Pure definitions and source receipts for canonical R5 monitoring owners."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from apps.fixed_income.domain.evidence import canonical_hash
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringCalendar,
    R5MonitoringPolicy,
    _require_aware,
    _require_hash,
    _require_token,
)


class R5MonitoringOwnerRecordKind(StrEnum):
    """The two independent Research-owned monitoring registries."""

    POLICY = "policy"
    CALENDAR = "calendar"


@dataclass(frozen=True)
class R5MonitoringPolicyDefinition:
    """One complete pre-existing Research policy owner definition."""

    policy: R5MonitoringPolicy
    content_hash: str = field(init=False)

    @classmethod
    def from_policy(cls, policy: R5MonitoringPolicy) -> R5MonitoringPolicyDefinition:
        """Copy an exact policy without accepting a caller-created registry row."""

        return cls(policy)

    def __post_init__(self) -> None:
        if type(self.policy) is not R5MonitoringPolicy:
            raise TypeError("R5 monitoring policy definition requires an exact policy")
        canonical = self.policy.validated_copy()
        if canonical != self.policy:
            raise ValueError("R5 monitoring policy definition was substituted")
        object.__setattr__(
            self,
            "content_hash",
            canonical_hash(
                {
                    "schema": "research-r5-monitoring-policy-definition.v1",
                    "policy": canonical,
                }
            ),
        )

    def validated_copy(self) -> R5MonitoringPolicyDefinition:
        """Deeply rebuild this definition and its policy."""

        copied = R5MonitoringPolicyDefinition.from_policy(self.policy.validated_copy())
        if copied != self:
            raise ValueError("R5 monitoring policy definition differs after replay")
        return copied


@dataclass(frozen=True)
class R5MonitoringCalendarDefinition:
    """One complete pre-existing Research calendar owner definition."""

    calendar: R5MonitoringCalendar
    content_hash: str = field(init=False)

    @classmethod
    def from_calendar(
        cls,
        calendar: R5MonitoringCalendar,
    ) -> R5MonitoringCalendarDefinition:
        """Copy an exact calendar without accepting a caller-created registry row."""

        return cls(calendar)

    def __post_init__(self) -> None:
        if type(self.calendar) is not R5MonitoringCalendar:
            raise TypeError("R5 monitoring calendar definition requires an exact calendar")
        canonical = self.calendar.validated_copy()
        if canonical != self.calendar:
            raise ValueError("R5 monitoring calendar definition was substituted")
        object.__setattr__(
            self,
            "content_hash",
            canonical_hash(
                {
                    "schema": "research-r5-monitoring-calendar-definition.v1",
                    "calendar": canonical,
                }
            ),
        )

    def validated_copy(self) -> R5MonitoringCalendarDefinition:
        """Deeply rebuild this definition and its calendar."""

        copied = R5MonitoringCalendarDefinition.from_calendar(self.calendar.validated_copy())
        if copied != self:
            raise ValueError("R5 monitoring calendar definition differs after replay")
        return copied


@dataclass(frozen=True)
class R5MonitoringOwnerSourceReceipt:
    """Independent Research source receipt binding one exact owner definition."""

    record_kind: R5MonitoringOwnerRecordKind
    source_owner: str
    source_receipt_id: str
    source_receipt_version: str
    owner_id: str
    owner_version: str
    definition_hash: str
    available_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        record_kind: R5MonitoringOwnerRecordKind,
        source_owner: str,
        source_receipt_id: str,
        source_receipt_version: str,
        owner_id: str,
        owner_version: str,
        definition_hash: str,
        available_at: datetime,
        valid_until: datetime,
    ) -> R5MonitoringOwnerSourceReceipt:
        """Create a content-addressed receipt without any default owner value."""

        digest = _source_receipt_hash(
            record_kind=record_kind,
            source_owner=source_owner,
            source_receipt_id=source_receipt_id,
            source_receipt_version=source_receipt_version,
            owner_id=owner_id,
            owner_version=owner_version,
            definition_hash=definition_hash,
            available_at=available_at,
            valid_until=valid_until,
        )
        return cls(
            record_kind=record_kind,
            source_owner=source_owner,
            source_receipt_id=source_receipt_id,
            source_receipt_version=source_receipt_version,
            owner_id=owner_id,
            owner_version=owner_version,
            definition_hash=definition_hash,
            available_at=available_at,
            valid_until=valid_until,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if type(self.record_kind) is not R5MonitoringOwnerRecordKind:
            raise TypeError("R5 monitoring owner receipt kind differs")
        if self.source_owner != "research":
            raise ValueError("R5 monitoring policy and calendar must be Research-owned")
        for label in (
            "source_owner",
            "source_receipt_id",
            "source_receipt_version",
            "owner_id",
            "owner_version",
        ):
            _require_token(getattr(self, label), f"R5 monitoring source {label}")
        _require_hash(self.definition_hash, "R5 monitoring source definition_hash")
        _require_hash(self.content_hash, "R5 monitoring source content_hash")
        _require_aware(self.available_at, "R5 monitoring source available_at")
        _require_aware(self.valid_until, "R5 monitoring source valid_until")
        if self.available_at >= self.valid_until:
            raise ValueError("R5 monitoring source receipt validity is empty")
        if self.content_hash != _source_receipt_hash(
            record_kind=self.record_kind,
            source_owner=self.source_owner,
            source_receipt_id=self.source_receipt_id,
            source_receipt_version=self.source_receipt_version,
            owner_id=self.owner_id,
            owner_version=self.owner_version,
            definition_hash=self.definition_hash,
            available_at=self.available_at,
            valid_until=self.valid_until,
        ):
            raise ValueError("R5 monitoring source receipt hash differs")

    def validated_copy(self) -> R5MonitoringOwnerSourceReceipt:
        """Rebuild the exact source receipt."""

        copied = R5MonitoringOwnerSourceReceipt.create(
            record_kind=self.record_kind,
            source_owner=self.source_owner,
            source_receipt_id=self.source_receipt_id,
            source_receipt_version=self.source_receipt_version,
            owner_id=self.owner_id,
            owner_version=self.owner_version,
            definition_hash=self.definition_hash,
            available_at=self.available_at,
            valid_until=self.valid_until,
        )
        if copied != self:
            raise ValueError("R5 monitoring source receipt differs after replay")
        return copied


def _source_receipt_hash(
    *,
    record_kind: R5MonitoringOwnerRecordKind,
    source_owner: str,
    source_receipt_id: str,
    source_receipt_version: str,
    owner_id: str,
    owner_version: str,
    definition_hash: str,
    available_at: datetime,
    valid_until: datetime,
) -> str:
    return canonical_hash(
        {
            "schema": "research-r5-monitoring-owner-source-receipt.v1",
            "kind": record_kind,
            "source": (source_owner, source_receipt_id, source_receipt_version),
            "owner": (owner_id, owner_version),
            "definition_hash": definition_hash,
            "window": (available_at, valid_until),
        }
    )


__all__ = [
    "R5MonitoringCalendarDefinition",
    "R5MonitoringOwnerRecordKind",
    "R5MonitoringOwnerSourceReceipt",
    "R5MonitoringPolicyDefinition",
]
