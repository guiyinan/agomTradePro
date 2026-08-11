"""Portfolio-owned source contracts for the R8 monitoring calendar registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from apps.portfolio.domain._optimization_canonical import (
    hash_components,
    require_aware,
    require_sha256,
    require_token,
    utc_text,
)
from apps.portfolio.domain.governed_optimization_monitoring import (
    GovernedOptimizationMonitoringCalendar,
    OptimizationMonitoringPeriod,
)
from apps.portfolio.domain.governed_optimization_monitoring_contracts import (
    MONITORING_CALENDAR_VERSION,
)

CALENDAR_DEFINITION_VERSION = "r8-monitoring-calendar-definition.v1"
CALENDAR_SOURCE_RECEIPT_VERSION = "r8-monitoring-calendar-source.v1"


def _utc(value: datetime, field_name: str) -> datetime:
    require_aware(value, field_name)
    return value.astimezone(UTC)


def _canonical_periods(
    *,
    calendar_id: str,
    calendar_version: str,
    periods: tuple[OptimizationMonitoringPeriod, ...],
) -> tuple[OptimizationMonitoringPeriod, ...]:
    if type(periods) is not tuple or not periods:
        raise ValueError("R8 calendar definition requires complete period membership")
    canonical: list[OptimizationMonitoringPeriod] = []
    for period in periods:
        if type(period) is not OptimizationMonitoringPeriod:
            raise TypeError("R8 calendar period must use the exact Domain type")
        OptimizationMonitoringPeriod.__post_init__(period)
        rebuilt = OptimizationMonitoringPeriod.create(
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            index=period.index,
            start_at=_utc(period.start_at, "calendar period start_at"),
            end_at=_utc(period.end_at, "calendar period end_at"),
        )
        if rebuilt.period_id != period.period_id:
            raise ValueError("R8 calendar period identity is noncanonical")
        canonical.append(rebuilt)
    return tuple(canonical)


@dataclass(frozen=True)
class R8MonitoringCalendarDefinition:
    """Complete calendar membership before Portfolio claims its server clock."""

    definition_version: str
    calendar_id: str
    calendar_version: str
    periods: tuple[OptimizationMonitoringPeriod, ...]
    available_at: datetime
    valid_until: datetime
    evidence_ref: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        calendar_id: str,
        calendar_version: str,
        periods: tuple[OptimizationMonitoringPeriod, ...],
        available_at: datetime,
        valid_until: datetime,
        evidence_ref: str,
    ) -> R8MonitoringCalendarDefinition:
        """Canonicalize complete membership and seal the owner-neutral definition."""

        canonical_periods = _canonical_periods(
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            periods=periods,
        )
        canonical_available_at = _utc(available_at, "calendar definition available_at")
        canonical_valid_until = _utc(valid_until, "calendar definition valid_until")
        values = (
            CALENDAR_DEFINITION_VERSION,
            calendar_id,
            calendar_version,
            canonical_periods,
            canonical_available_at,
            canonical_valid_until,
            evidence_ref,
        )
        return cls(*values, _definition_hash(*values))

    def __post_init__(self) -> None:
        if self.definition_version != CALENDAR_DEFINITION_VERSION:
            raise ValueError("R8 monitoring calendar definition version is unsupported")
        require_token(self.calendar_id, "R8 calendar definition calendar_id")
        require_token(self.calendar_version, "R8 calendar definition calendar_version")
        if self.calendar_version != MONITORING_CALENDAR_VERSION:
            raise ValueError("R8 monitoring calendar version is unsupported")
        canonical = _canonical_periods(
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            periods=self.periods,
        )
        if canonical != self.periods:
            raise ValueError("R8 monitoring calendar periods are noncanonical")
        require_aware(self.available_at, "R8 calendar definition available_at")
        require_aware(self.valid_until, "R8 calendar definition valid_until")
        require_token(self.evidence_ref, "R8 calendar definition evidence_ref")
        if not self.available_at <= self.periods[0].start_at:
            raise ValueError("R8 calendar definition arrived after its first period")
        if self.valid_until <= self.periods[-1].end_at:
            raise ValueError("R8 calendar definition validity does not cover all periods")
        require_sha256(self.content_hash, "R8 calendar definition content_hash")
        if self.content_hash != _definition_hash(
            self.definition_version,
            self.calendar_id,
            self.calendar_version,
            self.periods,
            self.available_at,
            self.valid_until,
            self.evidence_ref,
        ):
            raise ValueError("R8 monitoring calendar definition hash mismatch")

    def build(self, *, owner_recorded_at: datetime) -> GovernedOptimizationMonitoringCalendar:
        """Build a Portfolio calendar using only a trusted owner clock."""

        R8MonitoringCalendarDefinition.__post_init__(self)
        recorded_at = _utc(owner_recorded_at, "R8 calendar owner_recorded_at")
        if not self.available_at <= recorded_at <= self.periods[0].start_at:
            raise ValueError("R8 calendar owner clock is outside the definition window")
        return GovernedOptimizationMonitoringCalendar.create(
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            owner="portfolio",
            periods=_canonical_periods(
                calendar_id=self.calendar_id,
                calendar_version=self.calendar_version,
                periods=self.periods,
            ),
            recorded_at=recorded_at,
            valid_until=_utc(self.valid_until, "R8 calendar valid_until"),
        )

    def validated_copy(self) -> R8MonitoringCalendarDefinition:
        """Return a recursively rebuilt exact Domain value."""

        if type(self) is not R8MonitoringCalendarDefinition:
            raise TypeError("R8 calendar definition must use the exact Domain type")
        R8MonitoringCalendarDefinition.__post_init__(self)
        copied = R8MonitoringCalendarDefinition.create(
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            periods=self.periods,
            available_at=self.available_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
        )
        if copied.content_hash != self.content_hash:
            raise ValueError("R8 monitoring calendar definition is noncanonical")
        return copied


def _definition_hash(
    definition_version: str,
    calendar_id: str,
    calendar_version: str,
    periods: tuple[OptimizationMonitoringPeriod, ...],
    available_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
) -> str:
    return hash_components(
        definition_version,
        calendar_id,
        calendar_version,
        *(f"{item.period_id}|{item.index}|{utc_text(item.start_at)}|{utc_text(item.end_at)}" for item in periods),
        utc_text(available_at),
        utc_text(valid_until),
        evidence_ref,
    )


@dataclass(frozen=True)
class R8MonitoringCalendarSourceReceipt:
    """Portfolio source receipt authorizing one exact calendar definition."""

    source_owner: str
    source_receipt_id: str
    source_receipt_version: str
    definition_hash: str
    available_at: datetime
    valid_until: datetime
    evidence_ref: str
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
        evidence_ref: str,
    ) -> R8MonitoringCalendarSourceReceipt:
        """Seal one exact Portfolio-owned definition authorization."""

        values = (
            "portfolio",
            source_receipt_id,
            source_receipt_version,
            definition_hash.lower(),
            _utc(available_at, "R8 calendar source available_at"),
            _utc(valid_until, "R8 calendar source valid_until"),
            evidence_ref,
        )
        return cls(*values, _source_hash(*values))

    def __post_init__(self) -> None:
        if self.source_owner != "portfolio":
            raise ValueError("R8 monitoring calendar source owner must be Portfolio")
        require_token(self.source_receipt_id, "R8 calendar source_receipt_id")
        require_token(self.source_receipt_version, "R8 calendar source_receipt_version")
        if self.source_receipt_version != CALENDAR_SOURCE_RECEIPT_VERSION:
            raise ValueError("R8 monitoring calendar source version is unsupported")
        require_sha256(self.definition_hash, "R8 calendar source definition_hash")
        require_aware(self.available_at, "R8 calendar source available_at")
        require_aware(self.valid_until, "R8 calendar source valid_until")
        require_token(self.evidence_ref, "R8 calendar source evidence_ref")
        if self.available_at >= self.valid_until:
            raise ValueError("R8 monitoring calendar source is already expired")
        require_sha256(self.content_hash, "R8 calendar source content_hash")
        if self.content_hash != _source_hash(
            self.source_owner,
            self.source_receipt_id,
            self.source_receipt_version,
            self.definition_hash,
            self.available_at,
            self.valid_until,
            self.evidence_ref,
        ):
            raise ValueError("R8 monitoring calendar source hash mismatch")

    def validated_copy(self) -> R8MonitoringCalendarSourceReceipt:
        """Return a class-bound reconstructed source receipt."""

        if type(self) is not R8MonitoringCalendarSourceReceipt:
            raise TypeError("R8 calendar source must use the exact Domain type")
        R8MonitoringCalendarSourceReceipt.__post_init__(self)
        copied = R8MonitoringCalendarSourceReceipt.create(
            source_receipt_id=self.source_receipt_id,
            source_receipt_version=self.source_receipt_version,
            definition_hash=self.definition_hash,
            available_at=self.available_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
        )
        if copied.content_hash != self.content_hash:
            raise ValueError("R8 monitoring calendar source is noncanonical")
        return copied


def _source_hash(
    source_owner: str,
    source_receipt_id: str,
    source_receipt_version: str,
    definition_hash: str,
    available_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
) -> str:
    return hash_components(
        CALENDAR_SOURCE_RECEIPT_VERSION,
        source_owner,
        source_receipt_id,
        source_receipt_version,
        definition_hash.lower(),
        utc_text(available_at),
        utc_text(valid_until),
        evidence_ref,
    )


__all__ = [
    "CALENDAR_DEFINITION_VERSION",
    "CALENDAR_SOURCE_RECEIPT_VERSION",
    "R8MonitoringCalendarDefinition",
    "R8MonitoringCalendarSourceReceipt",
]
