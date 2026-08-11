"""Broker-owned raw reconciliation contracts for R8 monitoring."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

DEFINITION_VERSION = "broker-r8-reconciliation-definition.v1"
SOURCE_RECEIPT_VERSION = "broker-r8-reconciliation-source.v1"
PERIOD_RECEIPT_VERSION = "broker-r8-monitoring-period-receipt.v1"


class R8BrokerMonitoringMetricKey(StrEnum):
    """Exact Broker-owned metric set consumed by R8 monitoring."""

    TOTAL_COST_RATE = "total_cost_rate"
    ADVERSE_SLIPPAGE_RATE = "adverse_slippage_rate"
    RECONCILIATION_BREAK_RATE = "reconciliation_break_rate"


class R8BrokerReconciliationMemberKind(StrEnum):
    """Canonical source manifests required for one complete period."""

    FILL_MANIFEST = "fill_manifest"
    ORDER_PLAN_BINDING = "order_plan_binding"
    RECONCILIATION_MANIFEST = "reconciliation_manifest"


_RAW_SEMANTICS: dict[R8BrokerMonitoringMetricKey, tuple[str, str]] = {
    R8BrokerMonitoringMetricKey.TOTAL_COST_RATE: (
        "actual_total_cost_amount",
        "executed_notional",
    ),
    R8BrokerMonitoringMetricKey.ADVERSE_SLIPPAGE_RATE: (
        "adverse_slippage_amount",
        "executed_notional",
    ),
    R8BrokerMonitoringMetricKey.RECONCILIATION_BREAK_RATE: (
        "reconciliation_break_count",
        "reconciliation_comparison_count",
    ),
}


def _require_token(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty exact string")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    text = _require_token(value, field_name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return text


def _utc(value: datetime, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be an exact timezone-aware datetime")
    return value.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return _utc(value, "canonical datetime").isoformat(timespec="microseconds")


def _decimal_text(value: Decimal, field_name: str) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{field_name} must be an exact finite Decimal")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _hash_components(*components: str) -> str:
    digest = hashlib.sha256()
    for component in components:
        encoded = component.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


@dataclass(frozen=True)
class R8BrokerReconciliationMember:
    """One versioned source manifest with preserved owner clocks."""

    member_id: str
    member_version: str
    member_kind: R8BrokerReconciliationMemberKind
    content_hash: str
    observed_at: datetime
    available_at: datetime

    @classmethod
    def create(
        cls,
        *,
        member_id: str,
        member_version: str,
        member_kind: R8BrokerReconciliationMemberKind,
        content_hash: str,
        observed_at: datetime,
        available_at: datetime,
    ) -> R8BrokerReconciliationMember:
        """Canonicalize one independently sealed source member."""

        return cls(
            member_id=member_id,
            member_version=member_version,
            member_kind=member_kind,
            content_hash=content_hash.lower(),
            observed_at=_utc(observed_at, "Broker member observed_at"),
            available_at=_utc(available_at, "Broker member available_at"),
        )

    def __post_init__(self) -> None:
        _require_token(self.member_id, "Broker member_id")
        _require_token(self.member_version, "Broker member_version")
        if type(self.member_kind) is not R8BrokerReconciliationMemberKind:
            raise TypeError("Broker member_kind must use the exact enum")
        _require_sha256(self.content_hash, "Broker member content_hash")
        observed_at = _utc(self.observed_at, "Broker member observed_at")
        available_at = _utc(self.available_at, "Broker member available_at")
        if self.observed_at != observed_at or self.available_at != available_at:
            raise ValueError("Broker member clocks must be canonical UTC")
        if available_at < observed_at:
            raise ValueError("Broker member availability cannot predate observation")

    def validated_copy(self) -> R8BrokerReconciliationMember:
        """Return an exact class-bound reconstruction."""

        if type(self) is not R8BrokerReconciliationMember:
            raise TypeError("Broker member must use the exact Domain type")
        R8BrokerReconciliationMember.__post_init__(self)
        return R8BrokerReconciliationMember.create(
            member_id=self.member_id,
            member_version=self.member_version,
            member_kind=self.member_kind,
            content_hash=self.content_hash,
            observed_at=self.observed_at,
            available_at=self.available_at,
        )


@dataclass(frozen=True)
class R8BrokerMonitoringMetricRawFact:
    """Raw numerator and denominator; never a caller-supplied ratio alone."""

    metric_key: R8BrokerMonitoringMetricKey
    numerator_name: str
    numerator: Decimal
    denominator_name: str
    denominator: Decimal
    source_member_hashes: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        metric_key: R8BrokerMonitoringMetricKey,
        numerator_name: str,
        numerator: Decimal,
        denominator_name: str,
        denominator: Decimal,
        source_member_hashes: tuple[str, ...],
    ) -> R8BrokerMonitoringMetricRawFact:
        """Seal one canonical raw ratio input with exact source manifests."""

        if type(source_member_hashes) is not tuple:
            raise TypeError("Broker raw metric source hashes must be an exact tuple")
        canonical_hashes = tuple(item.lower() for item in source_member_hashes)
        digest = _raw_fact_hash(
            metric_key,
            numerator_name,
            numerator,
            denominator_name,
            denominator,
            canonical_hashes,
        )
        return cls(
            metric_key=metric_key,
            numerator_name=numerator_name,
            numerator=numerator,
            denominator_name=denominator_name,
            denominator=denominator,
            source_member_hashes=canonical_hashes,
            content_hash=digest,
        )

    @property
    def value(self) -> Decimal:
        """Derive the monitoring value from the sealed raw components."""

        R8BrokerMonitoringMetricRawFact.__post_init__(self)
        return self.numerator / self.denominator

    def __post_init__(self) -> None:
        if type(self.metric_key) is not R8BrokerMonitoringMetricKey:
            raise TypeError("Broker raw metric key must use the exact enum")
        numerator_name = _require_token(self.numerator_name, "Broker numerator_name")
        denominator_name = _require_token(self.denominator_name, "Broker denominator_name")
        if (numerator_name, denominator_name) != _RAW_SEMANTICS[self.metric_key]:
            raise ValueError("Broker raw metric semantics differ from the versioned contract")
        _decimal_text(self.numerator, "Broker raw numerator")
        _decimal_text(self.denominator, "Broker raw denominator")
        if self.numerator < 0 or self.denominator <= 0 or self.numerator > self.denominator:
            raise ValueError(
                "Broker raw ratio components must satisfy 0 <= numerator <= denominator"
            )
        if type(self.source_member_hashes) is not tuple or not self.source_member_hashes:
            raise TypeError("Broker raw metric source hashes must be a non-empty tuple")
        for source_hash in self.source_member_hashes:
            _require_sha256(source_hash, "Broker raw metric source member hash")
        if len(set(self.source_member_hashes)) != len(self.source_member_hashes):
            raise ValueError("Broker raw metric source member hashes must be unique")
        if self.metric_key is R8BrokerMonitoringMetricKey.RECONCILIATION_BREAK_RATE and (
            self.numerator != self.numerator.to_integral_value()
            or self.denominator != self.denominator.to_integral_value()
        ):
            raise ValueError("Broker reconciliation counts must be integral")
        _require_sha256(self.content_hash, "Broker raw metric content_hash")
        if self.content_hash != _raw_fact_hash(
            self.metric_key,
            self.numerator_name,
            self.numerator,
            self.denominator_name,
            self.denominator,
            self.source_member_hashes,
        ):
            raise ValueError("Broker raw metric content hash mismatch")

    def validated_copy(self) -> R8BrokerMonitoringMetricRawFact:
        """Return a recursively validated exact raw fact."""

        if type(self) is not R8BrokerMonitoringMetricRawFact:
            raise TypeError("Broker raw metric must use the exact Domain type")
        R8BrokerMonitoringMetricRawFact.__post_init__(self)
        copied = R8BrokerMonitoringMetricRawFact.create(
            metric_key=self.metric_key,
            numerator_name=self.numerator_name,
            numerator=self.numerator,
            denominator_name=self.denominator_name,
            denominator=self.denominator,
            source_member_hashes=self.source_member_hashes,
        )
        if copied.content_hash != self.content_hash:
            raise ValueError("Broker raw metric is noncanonical")
        return copied


def _raw_fact_hash(
    metric_key: R8BrokerMonitoringMetricKey,
    numerator_name: str,
    numerator: Decimal,
    denominator_name: str,
    denominator: Decimal,
    source_member_hashes: tuple[str, ...],
) -> str:
    return _hash_components(
        "broker-r8-monitoring-raw-ratio.v1",
        metric_key.value,
        numerator_name,
        _decimal_text(numerator, "Broker raw numerator"),
        denominator_name,
        _decimal_text(denominator, "Broker raw denominator"),
        *source_member_hashes,
    )


def _canonical_members(
    members: tuple[R8BrokerReconciliationMember, ...],
) -> tuple[R8BrokerReconciliationMember, ...]:
    if type(members) is not tuple:
        raise TypeError("Broker definition members must be a tuple")
    copied = tuple(item.validated_copy() for item in members)
    if tuple(item.member_kind for item in copied) != tuple(R8BrokerReconciliationMemberKind):
        raise ValueError("Broker definition requires one canonical source manifest per kind")
    if len({item.content_hash for item in copied}) != len(copied):
        raise ValueError("Broker definition source manifest hashes must be unique")
    return copied


def _canonical_facts(
    facts: tuple[R8BrokerMonitoringMetricRawFact, ...],
    members: tuple[R8BrokerReconciliationMember, ...],
) -> tuple[R8BrokerMonitoringMetricRawFact, ...]:
    if type(facts) is not tuple:
        raise TypeError("Broker definition raw facts must be a tuple")
    copied = tuple(item.validated_copy() for item in facts)
    if tuple(item.metric_key for item in copied) != tuple(R8BrokerMonitoringMetricKey):
        raise ValueError("Broker definition requires the canonical three raw metrics")
    member_hashes = {item.content_hash for item in members}
    if any(not set(item.source_member_hashes) <= member_hashes for item in copied):
        raise ValueError("Broker raw metric references an unknown source manifest")
    expected_sources = (
        (members[0].content_hash,),
        (members[0].content_hash, members[1].content_hash),
        (members[2].content_hash,),
    )
    if tuple(item.source_member_hashes for item in copied) != expected_sources:
        raise ValueError("Broker raw metric source binding differs from the contract")
    return copied


@dataclass(frozen=True)
class R8BrokerReconciliationDefinition:
    """Complete Broker period definition with raw ratios and cross-owner identities."""

    definition_id: str
    definition_version: str
    result_id: str
    result_hash: str
    portfolio_receipt_id: str
    portfolio_receipt_version: str
    portfolio_receipt_hash: str
    calendar_id: str
    calendar_version: str
    calendar_hash: str
    period_id: str
    period_start_at: datetime
    period_end_at: datetime
    planning_reference_id: str
    planning_reference_version: str
    planning_reference_hash: str
    reconciliation_manifest_id: str
    reconciliation_manifest_version: str
    reconciliation_manifest_hash: str
    members: tuple[R8BrokerReconciliationMember, ...]
    metric_facts: tuple[R8BrokerMonitoringMetricRawFact, ...]
    observed_at: datetime
    available_at: datetime
    valid_until: datetime
    evidence_ref: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        result_id: str,
        result_hash: str,
        portfolio_receipt_id: str,
        portfolio_receipt_version: str,
        portfolio_receipt_hash: str,
        calendar_id: str,
        calendar_version: str,
        calendar_hash: str,
        period_id: str,
        period_start_at: datetime,
        period_end_at: datetime,
        planning_reference_id: str,
        planning_reference_version: str,
        planning_reference_hash: str,
        reconciliation_manifest_id: str,
        reconciliation_manifest_version: str,
        reconciliation_manifest_hash: str,
        members: tuple[R8BrokerReconciliationMember, ...],
        metric_facts: tuple[R8BrokerMonitoringMetricRawFact, ...],
        valid_until: datetime,
        evidence_ref: str,
    ) -> R8BrokerReconciliationDefinition:
        """Seal the complete definition without accepting aggregate metric values."""

        canonical_members = _canonical_members(members)
        canonical_facts = _canonical_facts(metric_facts, canonical_members)
        observed_at = max(item.observed_at for item in canonical_members)
        available_at = max(item.available_at for item in canonical_members)
        values = (
            DEFINITION_VERSION,
            result_id,
            result_hash.lower(),
            portfolio_receipt_id,
            portfolio_receipt_version,
            portfolio_receipt_hash.lower(),
            calendar_id,
            calendar_version,
            calendar_hash.lower(),
            period_id,
            _utc(period_start_at, "Broker period_start_at"),
            _utc(period_end_at, "Broker period_end_at"),
            planning_reference_id,
            planning_reference_version,
            planning_reference_hash.lower(),
            reconciliation_manifest_id,
            reconciliation_manifest_version,
            reconciliation_manifest_hash.lower(),
            canonical_members,
            canonical_facts,
            observed_at,
            available_at,
            _utc(valid_until, "Broker definition valid_until"),
            evidence_ref,
        )
        digest = _definition_hash(*values)
        return cls(
            definition_id=f"broker-r8-reconciliation-definition:{digest[:24]}",
            definition_version=values[0],
            result_id=values[1],
            result_hash=values[2],
            portfolio_receipt_id=values[3],
            portfolio_receipt_version=values[4],
            portfolio_receipt_hash=values[5],
            calendar_id=values[6],
            calendar_version=values[7],
            calendar_hash=values[8],
            period_id=values[9],
            period_start_at=values[10],
            period_end_at=values[11],
            planning_reference_id=values[12],
            planning_reference_version=values[13],
            planning_reference_hash=values[14],
            reconciliation_manifest_id=values[15],
            reconciliation_manifest_version=values[16],
            reconciliation_manifest_hash=values[17],
            members=values[18],
            metric_facts=values[19],
            observed_at=values[20],
            available_at=values[21],
            valid_until=values[22],
            evidence_ref=values[23],
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if self.definition_version != DEFINITION_VERSION:
            raise ValueError("Broker reconciliation definition version is unsupported")
        for label, value in (
            ("definition_id", self.definition_id),
            ("result_id", self.result_id),
            ("portfolio_receipt_id", self.portfolio_receipt_id),
            ("portfolio_receipt_version", self.portfolio_receipt_version),
            ("calendar_id", self.calendar_id),
            ("calendar_version", self.calendar_version),
            ("period_id", self.period_id),
            ("planning_reference_id", self.planning_reference_id),
            ("planning_reference_version", self.planning_reference_version),
            ("reconciliation_manifest_id", self.reconciliation_manifest_id),
            ("reconciliation_manifest_version", self.reconciliation_manifest_version),
            ("evidence_ref", self.evidence_ref),
        ):
            _require_token(value, f"Broker definition {label}")
        for label, value in (
            ("result_hash", self.result_hash),
            ("portfolio_receipt_hash", self.portfolio_receipt_hash),
            ("calendar_hash", self.calendar_hash),
            ("planning_reference_hash", self.planning_reference_hash),
            ("reconciliation_manifest_hash", self.reconciliation_manifest_hash),
            ("content_hash", self.content_hash),
        ):
            _require_sha256(value, f"Broker definition {label}")
        members = _canonical_members(self.members)
        facts = _canonical_facts(self.metric_facts, members)
        start = _utc(self.period_start_at, "Broker definition period_start_at")
        end = _utc(self.period_end_at, "Broker definition period_end_at")
        observed = _utc(self.observed_at, "Broker definition observed_at")
        available = _utc(self.available_at, "Broker definition available_at")
        valid_until = _utc(self.valid_until, "Broker definition valid_until")
        if (
            self.period_start_at != start
            or self.period_end_at != end
            or self.observed_at != observed
            or self.available_at != available
            or self.valid_until != valid_until
        ):
            raise ValueError("Broker definition clocks must be canonical UTC")
        if not start < end or any(not start <= item.observed_at <= end for item in members):
            raise ValueError("Broker source observations must lie inside the exact period")
        if observed != max(item.observed_at for item in members):
            raise ValueError("Broker definition observed_at must preserve the latest source clock")
        if available != max(item.available_at for item in members):
            raise ValueError("Broker definition available_at must preserve source availability")
        if not observed <= available < valid_until:
            raise ValueError("Broker definition validity clocks are invalid")
        plan_member = members[1]
        reconciliation_member = members[2]
        if (plan_member.member_id, plan_member.member_version, plan_member.content_hash) != (
            self.planning_reference_id,
            self.planning_reference_version,
            self.planning_reference_hash,
        ) or (
            reconciliation_member.member_id,
            reconciliation_member.member_version,
            reconciliation_member.content_hash,
        ) != (
            self.reconciliation_manifest_id,
            self.reconciliation_manifest_version,
            self.reconciliation_manifest_hash,
        ):
            raise ValueError("Broker definition manifest headers differ from source members")
        expected_hash = _definition_hash(
            self.definition_version,
            self.result_id,
            self.result_hash,
            self.portfolio_receipt_id,
            self.portfolio_receipt_version,
            self.portfolio_receipt_hash,
            self.calendar_id,
            self.calendar_version,
            self.calendar_hash,
            self.period_id,
            self.period_start_at,
            self.period_end_at,
            self.planning_reference_id,
            self.planning_reference_version,
            self.planning_reference_hash,
            self.reconciliation_manifest_id,
            self.reconciliation_manifest_version,
            self.reconciliation_manifest_hash,
            members,
            facts,
            self.observed_at,
            self.available_at,
            self.valid_until,
            self.evidence_ref,
        )
        if self.content_hash != expected_hash:
            raise ValueError("Broker reconciliation definition content hash mismatch")
        if self.definition_id != f"broker-r8-reconciliation-definition:{expected_hash[:24]}":
            raise ValueError("Broker reconciliation definition identity mismatch")

    def validated_copy(self) -> R8BrokerReconciliationDefinition:
        """Return a recursively rebuilt exact definition."""

        if type(self) is not R8BrokerReconciliationDefinition:
            raise TypeError("Broker definition must use the exact Domain type")
        R8BrokerReconciliationDefinition.__post_init__(self)
        copied = R8BrokerReconciliationDefinition.create(
            result_id=self.result_id,
            result_hash=self.result_hash,
            portfolio_receipt_id=self.portfolio_receipt_id,
            portfolio_receipt_version=self.portfolio_receipt_version,
            portfolio_receipt_hash=self.portfolio_receipt_hash,
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            calendar_hash=self.calendar_hash,
            period_id=self.period_id,
            period_start_at=self.period_start_at,
            period_end_at=self.period_end_at,
            planning_reference_id=self.planning_reference_id,
            planning_reference_version=self.planning_reference_version,
            planning_reference_hash=self.planning_reference_hash,
            reconciliation_manifest_id=self.reconciliation_manifest_id,
            reconciliation_manifest_version=self.reconciliation_manifest_version,
            reconciliation_manifest_hash=self.reconciliation_manifest_hash,
            members=self.members,
            metric_facts=self.metric_facts,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
        )
        if copied != self:
            raise ValueError("Broker reconciliation definition is noncanonical")
        return copied


def _definition_hash(
    definition_version: str,
    result_id: str,
    result_hash: str,
    portfolio_receipt_id: str,
    portfolio_receipt_version: str,
    portfolio_receipt_hash: str,
    calendar_id: str,
    calendar_version: str,
    calendar_hash: str,
    period_id: str,
    period_start_at: datetime,
    period_end_at: datetime,
    planning_reference_id: str,
    planning_reference_version: str,
    planning_reference_hash: str,
    reconciliation_manifest_id: str,
    reconciliation_manifest_version: str,
    reconciliation_manifest_hash: str,
    members: tuple[R8BrokerReconciliationMember, ...],
    metric_facts: tuple[R8BrokerMonitoringMetricRawFact, ...],
    observed_at: datetime,
    available_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
) -> str:
    return _hash_components(
        definition_version,
        result_id,
        result_hash,
        portfolio_receipt_id,
        portfolio_receipt_version,
        portfolio_receipt_hash,
        calendar_id,
        calendar_version,
        calendar_hash,
        period_id,
        _utc_text(period_start_at),
        _utc_text(period_end_at),
        planning_reference_id,
        planning_reference_version,
        planning_reference_hash,
        reconciliation_manifest_id,
        reconciliation_manifest_version,
        reconciliation_manifest_hash,
        *(
            f"{item.member_kind.value}|{item.member_id}|{item.member_version}|"
            f"{item.content_hash}|{_utc_text(item.observed_at)}|{_utc_text(item.available_at)}"
            for item in members
        ),
        *(item.content_hash for item in metric_facts),
        _utc_text(observed_at),
        _utc_text(available_at),
        _utc_text(valid_until),
        evidence_ref,
    )


@dataclass(frozen=True)
class R8BrokerReconciliationSourceReceipt:
    """Independent Broker source authorization for one exact definition."""

    owner: str
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
    ) -> R8BrokerReconciliationSourceReceipt:
        """Seal one exact source authorization without accepting raw facts."""

        values = (
            "broker_execution",
            source_receipt_id,
            source_receipt_version,
            definition_hash.lower(),
            _utc(available_at, "Broker source available_at"),
            _utc(valid_until, "Broker source valid_until"),
            evidence_ref,
        )
        return cls(*values, _source_receipt_hash(*values))

    def __post_init__(self) -> None:
        if self.owner != "broker_execution":
            raise ValueError("Broker reconciliation source owner is invalid")
        _require_token(self.source_receipt_id, "Broker source_receipt_id")
        if self.source_receipt_version != SOURCE_RECEIPT_VERSION:
            raise ValueError("Broker reconciliation source version is unsupported")
        _require_sha256(self.definition_hash, "Broker source definition_hash")
        available = _utc(self.available_at, "Broker source available_at")
        valid_until = _utc(self.valid_until, "Broker source valid_until")
        _require_token(self.evidence_ref, "Broker source evidence_ref")
        if self.available_at != available or self.valid_until != valid_until:
            raise ValueError("Broker source clocks must be canonical UTC")
        if available >= valid_until:
            raise ValueError("Broker reconciliation source is already expired")
        _require_sha256(self.content_hash, "Broker source content_hash")
        if self.content_hash != _source_receipt_hash(
            self.owner,
            self.source_receipt_id,
            self.source_receipt_version,
            self.definition_hash,
            self.available_at,
            self.valid_until,
            self.evidence_ref,
        ):
            raise ValueError("Broker reconciliation source hash mismatch")

    def validated_copy(self) -> R8BrokerReconciliationSourceReceipt:
        """Return a class-bound exact source receipt."""

        if type(self) is not R8BrokerReconciliationSourceReceipt:
            raise TypeError("Broker source receipt must use the exact Domain type")
        R8BrokerReconciliationSourceReceipt.__post_init__(self)
        copied = R8BrokerReconciliationSourceReceipt.create(
            source_receipt_id=self.source_receipt_id,
            source_receipt_version=self.source_receipt_version,
            definition_hash=self.definition_hash,
            available_at=self.available_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
        )
        if copied != self:
            raise ValueError("Broker reconciliation source is noncanonical")
        return copied


def _source_receipt_hash(
    owner: str,
    source_receipt_id: str,
    source_receipt_version: str,
    definition_hash: str,
    available_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
) -> str:
    return _hash_components(
        SOURCE_RECEIPT_VERSION,
        owner,
        source_receipt_id,
        source_receipt_version,
        definition_hash,
        _utc_text(available_at),
        _utc_text(valid_until),
        evidence_ref,
    )


@dataclass(frozen=True)
class R8BrokerMonitoringPeriodReceipt:
    """Append-only Broker owner receipt over one complete period definition."""

    owner: str
    receipt_id: str
    receipt_version: str
    definition: R8BrokerReconciliationDefinition
    source_receipt: R8BrokerReconciliationSourceReceipt
    recorded_at: datetime
    research_only: bool
    must_not_use_for_decision: bool
    must_not_publish_current: bool
    must_not_execute: bool
    content_hash: str

    @classmethod
    def record(
        cls,
        *,
        definition: R8BrokerReconciliationDefinition,
        source_receipt: R8BrokerReconciliationSourceReceipt,
        owner_recorded_at: datetime,
    ) -> R8BrokerMonitoringPeriodReceipt:
        """Record canonical sources using only the Broker owner's trusted clock."""

        canonical_definition = definition.validated_copy()
        canonical_source = source_receipt.validated_copy()
        recorded_at = _utc(owner_recorded_at, "Broker owner recorded_at")
        digest = _period_receipt_hash(
            canonical_definition,
            canonical_source,
            recorded_at,
        )
        return cls(
            owner="broker_execution",
            receipt_id=f"broker-r8-monitoring-period-receipt:{digest[:24]}",
            receipt_version=PERIOD_RECEIPT_VERSION,
            definition=canonical_definition,
            source_receipt=canonical_source,
            recorded_at=recorded_at,
            research_only=True,
            must_not_use_for_decision=True,
            must_not_publish_current=True,
            must_not_execute=True,
            content_hash=digest,
        )

    @property
    def observed_at(self) -> datetime:
        """Return the preserved latest source observation clock."""

        return self.definition.observed_at

    @property
    def available_at(self) -> datetime:
        """Return the preserved latest source availability clock."""

        return self.definition.available_at

    @property
    def valid_until(self) -> datetime:
        """Return the earliest validity bound across both owner inputs."""

        return min(self.definition.valid_until, self.source_receipt.valid_until)

    def __post_init__(self) -> None:
        if self.owner != "broker_execution":
            raise ValueError("Broker monitoring period owner is invalid")
        _require_token(self.receipt_id, "Broker monitoring receipt_id")
        if self.receipt_version != PERIOD_RECEIPT_VERSION:
            raise ValueError("Broker monitoring period receipt version is unsupported")
        if type(self.definition) is not R8BrokerReconciliationDefinition:
            raise TypeError("Broker period definition must use the exact Domain type")
        if type(self.source_receipt) is not R8BrokerReconciliationSourceReceipt:
            raise TypeError("Broker period source must use the exact Domain type")
        definition = self.definition.validated_copy()
        source = self.source_receipt.validated_copy()
        recorded = _utc(self.recorded_at, "Broker monitoring recorded_at")
        if self.recorded_at != recorded:
            raise ValueError("Broker monitoring recorded_at must be canonical UTC")
        if (
            source.definition_hash != definition.content_hash
            or source.available_at < definition.available_at
            or source.valid_until < definition.valid_until
            or not max(definition.available_at, source.available_at)
            <= recorded
            < min(definition.valid_until, source.valid_until)
        ):
            raise ValueError("Broker monitoring owner graph clocks or hashes differ")
        for flag in (
            self.research_only,
            self.must_not_use_for_decision,
            self.must_not_publish_current,
            self.must_not_execute,
        ):
            if type(flag) is not bool or not flag:
                raise ValueError("Broker monitoring receipt safety flags must stay true")
        _require_sha256(self.content_hash, "Broker monitoring receipt content_hash")
        expected_hash = _period_receipt_hash(definition, source, recorded)
        if self.content_hash != expected_hash:
            raise ValueError("Broker monitoring period receipt hash mismatch")
        if self.receipt_id != f"broker-r8-monitoring-period-receipt:{expected_hash[:24]}":
            raise ValueError("Broker monitoring period receipt identity mismatch")

    def validated_copy(self) -> R8BrokerMonitoringPeriodReceipt:
        """Return a recursively rebuilt exact owner receipt."""

        if type(self) is not R8BrokerMonitoringPeriodReceipt:
            raise TypeError("Broker monitoring receipt must use the exact Domain type")
        R8BrokerMonitoringPeriodReceipt.__post_init__(self)
        copied = R8BrokerMonitoringPeriodReceipt.record(
            definition=self.definition,
            source_receipt=self.source_receipt,
            owner_recorded_at=self.recorded_at,
        )
        if copied != self:
            raise ValueError("Broker monitoring period receipt is noncanonical")
        return copied


def _period_receipt_hash(
    definition: R8BrokerReconciliationDefinition,
    source: R8BrokerReconciliationSourceReceipt,
    recorded_at: datetime,
) -> str:
    return _hash_components(
        PERIOD_RECEIPT_VERSION,
        "broker_execution",
        definition.content_hash,
        source.source_receipt_id,
        source.source_receipt_version,
        source.content_hash,
        _utc_text(recorded_at),
        "research_only",
        "must_not_use_for_decision",
        "must_not_publish_current",
        "must_not_execute",
    )


__all__ = [
    "DEFINITION_VERSION",
    "PERIOD_RECEIPT_VERSION",
    "SOURCE_RECEIPT_VERSION",
    "R8BrokerMonitoringMetricKey",
    "R8BrokerMonitoringMetricRawFact",
    "R8BrokerMonitoringPeriodReceipt",
    "R8BrokerReconciliationDefinition",
    "R8BrokerReconciliationMember",
    "R8BrokerReconciliationMemberKind",
    "R8BrokerReconciliationSourceReceipt",
]
