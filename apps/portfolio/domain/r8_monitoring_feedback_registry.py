"""Portfolio-owned raw R8 monitoring feedback contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from apps.fixed_income.domain.evidence import canonical_hash
from apps.portfolio.domain.governed_optimization_monitoring_metrics import (
    MonitoringMetricKey,
)

FEEDBACK_VERSION = "portfolio-r8-monitoring-feedback.v1"
FEEDBACK_DEFINITION_VERSION = "portfolio-r8-monitoring-feedback-definition.v1"
FEEDBACK_SOURCE_RECEIPT_VERSION = "portfolio-r8-monitoring-feedback-source.v1"


class PortfolioR8MonitoringMemberKind(StrEnum):
    """Seven canonical source members supporting eight Portfolio metrics."""

    PERFORMANCE_PATH = "performance_path"
    TURNOVER_LEDGER = "turnover_ledger"
    LIQUIDITY_LEDGER = "liquidity_ledger"
    CAPACITY_LEDGER = "capacity_ledger"
    CONSTRAINT_LEDGER = "constraint_ledger"
    LABEL_DRIFT_LEDGER = "label_drift_ledger"
    DATA_DRIFT_LEDGER = "data_drift_ledger"


_PORTFOLIO_METRIC_KEYS = (
    MonitoringMetricKey.NET_REALIZED_RETURN,
    MonitoringMetricKey.MAX_DRAWDOWN,
    MonitoringMetricKey.TURNOVER_RATE,
    MonitoringMetricKey.LIQUIDITY_UTILIZATION,
    MonitoringMetricKey.CAPACITY_UTILIZATION,
    MonitoringMetricKey.CONSTRAINT_BREACH_RATE,
    MonitoringMetricKey.LABEL_DRIFT_RATE,
    MonitoringMetricKey.DATA_DRIFT_SCORE,
)

_RAW_SEMANTICS: dict[MonitoringMetricKey, tuple[str, str, PortfolioR8MonitoringMemberKind]] = {
    MonitoringMetricKey.NET_REALIZED_RETURN: (
        "net_realized_pnl_after_flows",
        "opening_portfolio_value",
        PortfolioR8MonitoringMemberKind.PERFORMANCE_PATH,
    ),
    MonitoringMetricKey.MAX_DRAWDOWN: (
        "maximum_peak_to_trough_loss",
        "peak_portfolio_value",
        PortfolioR8MonitoringMemberKind.PERFORMANCE_PATH,
    ),
    MonitoringMetricKey.TURNOVER_RATE: (
        "absolute_traded_notional",
        "average_portfolio_value",
        PortfolioR8MonitoringMemberKind.TURNOVER_LEDGER,
    ),
    MonitoringMetricKey.LIQUIDITY_UTILIZATION: (
        "liquidity_consumed_notional",
        "liquidity_budget_notional",
        PortfolioR8MonitoringMemberKind.LIQUIDITY_LEDGER,
    ),
    MonitoringMetricKey.CAPACITY_UTILIZATION: (
        "position_exposure_notional",
        "capacity_limit_notional",
        PortfolioR8MonitoringMemberKind.CAPACITY_LEDGER,
    ),
    MonitoringMetricKey.CONSTRAINT_BREACH_RATE: (
        "constraint_breach_count",
        "constraint_evaluation_count",
        PortfolioR8MonitoringMemberKind.CONSTRAINT_LEDGER,
    ),
    MonitoringMetricKey.LABEL_DRIFT_RATE: (
        "changed_label_count",
        "comparable_label_count",
        PortfolioR8MonitoringMemberKind.LABEL_DRIFT_LEDGER,
    ),
    MonitoringMetricKey.DATA_DRIFT_SCORE: (
        "aggregate_drift_distance",
        "drift_normalization_bound",
        PortfolioR8MonitoringMemberKind.DATA_DRIFT_LEDGER,
    ),
}


def _token(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty exact string")
    return value


def _hash(value: object, label: str) -> str:
    text = _token(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _aware(value: datetime, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")
    return value


def _decimal(value: object, label: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{label} must be an exact finite Decimal")
    return value


@dataclass(frozen=True)
class PortfolioR8MonitoringSourceMember:
    """One exact Portfolio source member with owner observation clocks."""

    member_id: str
    member_version: str
    member_kind: PortfolioR8MonitoringMemberKind
    content_hash: str
    observed_at: datetime
    available_at: datetime

    @classmethod
    def create(
        cls,
        *,
        member_id: str,
        member_version: str,
        member_kind: PortfolioR8MonitoringMemberKind,
        content_hash: str,
        observed_at: datetime,
        available_at: datetime,
    ) -> PortfolioR8MonitoringSourceMember:
        """Create one exact source member without raw metric synthesis."""

        return cls(
            member_id=member_id,
            member_version=member_version,
            member_kind=member_kind,
            content_hash=content_hash,
            observed_at=observed_at,
            available_at=available_at,
        )

    def __post_init__(self) -> None:
        _token(self.member_id, "Portfolio R8 member_id")
        _token(self.member_version, "Portfolio R8 member_version")
        if type(self.member_kind) is not PortfolioR8MonitoringMemberKind:
            raise TypeError("Portfolio R8 member kind must use the exact enum")
        _hash(self.content_hash, "Portfolio R8 member content_hash")
        observed = _aware(self.observed_at, "Portfolio R8 member observed_at")
        available = _aware(self.available_at, "Portfolio R8 member available_at")
        if available < observed:
            raise ValueError("Portfolio R8 member availability predates observation")

    def validated_copy(self) -> PortfolioR8MonitoringSourceMember:
        """Return a class-bound exact reconstruction."""

        if type(self) is not PortfolioR8MonitoringSourceMember:
            raise TypeError("Portfolio R8 source member type differs")
        PortfolioR8MonitoringSourceMember.__post_init__(self)
        return PortfolioR8MonitoringSourceMember.create(
            member_id=self.member_id,
            member_version=self.member_version,
            member_kind=self.member_kind,
            content_hash=self.content_hash,
            observed_at=self.observed_at,
            available_at=self.available_at,
        )


@dataclass(frozen=True)
class PortfolioR8MonitoringRawRatio:
    """One raw numerator/denominator; the metric value is always derived live."""

    metric_key: MonitoringMetricKey
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
        metric_key: MonitoringMetricKey,
        numerator: Decimal,
        denominator: Decimal,
        source_member_hashes: tuple[str, ...],
    ) -> PortfolioR8MonitoringRawRatio:
        """Seal raw components using the versioned metric semantics table."""

        if type(metric_key) is not MonitoringMetricKey or metric_key not in _RAW_SEMANTICS:
            raise TypeError("Portfolio R8 raw metric key is not Portfolio-owned")
        if type(source_member_hashes) is not tuple:
            raise TypeError("Portfolio R8 raw source hashes must be an exact tuple")
        numerator_name, denominator_name, _ = _RAW_SEMANTICS[metric_key]
        values = (
            metric_key,
            numerator_name,
            numerator,
            denominator_name,
            denominator,
            source_member_hashes,
        )
        return cls(*values, _raw_ratio_hash(*values))

    @property
    def value(self) -> Decimal:
        """Derive the Phase A value from sealed raw components."""

        PortfolioR8MonitoringRawRatio.__post_init__(self)
        return self.numerator / self.denominator

    def __post_init__(self) -> None:
        if (
            type(self.metric_key) is not MonitoringMetricKey
            or self.metric_key not in _RAW_SEMANTICS
        ):
            raise TypeError("Portfolio R8 raw metric key is invalid")
        expected_names = _RAW_SEMANTICS[self.metric_key][:2]
        if (self.numerator_name, self.denominator_name) != expected_names:
            raise ValueError("Portfolio R8 raw metric semantics differ")
        numerator = _decimal(self.numerator, "Portfolio R8 raw numerator")
        denominator = _decimal(self.denominator, "Portfolio R8 raw denominator")
        if denominator <= 0:
            raise ValueError("Portfolio R8 raw denominator must be positive")
        value = numerator / denominator
        if self.metric_key is MonitoringMetricKey.NET_REALIZED_RETURN:
            if value < -1:
                raise ValueError("Portfolio R8 net realized return cannot be below -1")
        elif numerator < 0:
            raise ValueError("Portfolio R8 non-return numerators cannot be negative")
        if (
            self.metric_key
            in (
                MonitoringMetricKey.MAX_DRAWDOWN,
                MonitoringMetricKey.CONSTRAINT_BREACH_RATE,
                MonitoringMetricKey.LABEL_DRIFT_RATE,
                MonitoringMetricKey.DATA_DRIFT_SCORE,
            )
            and value > 1
        ):
            raise ValueError("Portfolio R8 bounded raw ratio cannot exceed 1")
        if self.metric_key in (
            MonitoringMetricKey.CONSTRAINT_BREACH_RATE,
            MonitoringMetricKey.LABEL_DRIFT_RATE,
        ) and (
            numerator != numerator.to_integral_value()
            or denominator != denominator.to_integral_value()
        ):
            raise ValueError("Portfolio R8 count ratios require integral raw values")
        if type(self.source_member_hashes) is not tuple or len(self.source_member_hashes) != 1:
            raise ValueError("Portfolio R8 raw metric requires one exact source member")
        _hash(self.source_member_hashes[0], "Portfolio R8 raw source member hash")
        _hash(self.content_hash, "Portfolio R8 raw content_hash")
        if self.content_hash != _raw_ratio_hash(
            self.metric_key,
            self.numerator_name,
            self.numerator,
            self.denominator_name,
            self.denominator,
            self.source_member_hashes,
        ):
            raise ValueError("Portfolio R8 raw metric content hash differs")

    def validated_copy(self) -> PortfolioR8MonitoringRawRatio:
        """Return a recursively revalidated raw ratio."""

        if type(self) is not PortfolioR8MonitoringRawRatio:
            raise TypeError("Portfolio R8 raw ratio type differs")
        copied = PortfolioR8MonitoringRawRatio.create(
            metric_key=self.metric_key,
            numerator=self.numerator,
            denominator=self.denominator,
            source_member_hashes=self.source_member_hashes,
        )
        if copied != self:
            raise ValueError("Portfolio R8 raw ratio differs after replay")
        return copied


def _raw_ratio_hash(
    metric_key: MonitoringMetricKey,
    numerator_name: str,
    numerator: Decimal,
    denominator_name: str,
    denominator: Decimal,
    source_member_hashes: tuple[str, ...],
) -> str:
    return canonical_hash(
        {
            "schema": "portfolio-r8-monitoring-raw-ratio.v1",
            "metric_key": metric_key,
            "numerator": (numerator_name, numerator),
            "denominator": (denominator_name, denominator),
            "source_member_hashes": source_member_hashes,
        }
    )


def _canonical_members(
    members: tuple[PortfolioR8MonitoringSourceMember, ...],
) -> tuple[PortfolioR8MonitoringSourceMember, ...]:
    if type(members) is not tuple:
        raise TypeError("Portfolio R8 feedback members must be a tuple")
    if any(type(item) is not PortfolioR8MonitoringSourceMember for item in members):
        raise TypeError("Portfolio R8 feedback member type is invalid")
    copied = tuple(PortfolioR8MonitoringSourceMember.validated_copy(item) for item in members)
    if tuple(item.member_kind for item in copied) != tuple(PortfolioR8MonitoringMemberKind):
        raise ValueError("Portfolio R8 feedback requires the canonical seven source members")
    if len({item.content_hash for item in copied}) != len(copied):
        raise ValueError("Portfolio R8 source member hashes must be unique")
    return copied


def _canonical_facts(
    facts: tuple[PortfolioR8MonitoringRawRatio, ...],
    members: tuple[PortfolioR8MonitoringSourceMember, ...],
) -> tuple[PortfolioR8MonitoringRawRatio, ...]:
    if type(facts) is not tuple:
        raise TypeError("Portfolio R8 feedback raw facts must be a tuple")
    if any(type(item) is not PortfolioR8MonitoringRawRatio for item in facts):
        raise TypeError("Portfolio R8 feedback raw fact type is invalid")
    copied = tuple(PortfolioR8MonitoringRawRatio.validated_copy(item) for item in facts)
    if tuple(item.metric_key for item in copied) != _PORTFOLIO_METRIC_KEYS:
        raise ValueError("Portfolio R8 feedback requires the canonical eight raw metrics")
    hashes = {item.member_kind: item.content_hash for item in members}
    expected = tuple((hashes[_RAW_SEMANTICS[item.metric_key][2]],) for item in copied)
    if tuple(item.source_member_hashes for item in copied) != expected:
        raise ValueError("Portfolio R8 raw metrics do not bind the canonical source members")
    return copied


@dataclass(frozen=True)
class PortfolioR8MonitoringFeedback:
    """One complete Portfolio period feedback graph with no aggregate inputs."""

    feedback_id: str
    feedback_version: str
    result_id: str
    result_version: str
    result_hash: str
    receipt_id: str
    receipt_version: str
    receipt_hash: str
    calendar_id: str
    calendar_version: str
    calendar_hash: str
    period_id: str
    period_start_at: datetime
    period_end_at: datetime
    members: tuple[PortfolioR8MonitoringSourceMember, ...]
    metric_facts: tuple[PortfolioR8MonitoringRawRatio, ...]
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
        result_version: str,
        result_hash: str,
        receipt_id: str,
        receipt_version: str,
        receipt_hash: str,
        calendar_id: str,
        calendar_version: str,
        calendar_hash: str,
        period_id: str,
        period_start_at: datetime,
        period_end_at: datetime,
        members: tuple[PortfolioR8MonitoringSourceMember, ...],
        metric_facts: tuple[PortfolioR8MonitoringRawRatio, ...],
        valid_until: datetime,
        evidence_ref: str,
    ) -> PortfolioR8MonitoringFeedback:
        """Seal exact identities and raw facts without accepting metric values."""

        canonical_members = _canonical_members(members)
        canonical_facts = _canonical_facts(metric_facts, canonical_members)
        observed_at = max(item.observed_at for item in canonical_members)
        available_at = max(item.available_at for item in canonical_members)
        digest = _feedback_hash(
            result_id=result_id,
            result_version=result_version,
            result_hash=result_hash,
            receipt_id=receipt_id,
            receipt_version=receipt_version,
            receipt_hash=receipt_hash,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_hash=calendar_hash,
            period_id=period_id,
            period_start_at=period_start_at,
            period_end_at=period_end_at,
            members=canonical_members,
            metric_facts=canonical_facts,
            observed_at=observed_at,
            available_at=available_at,
            valid_until=valid_until,
            evidence_ref=evidence_ref,
        )
        return cls(
            feedback_id=f"portfolio-r8-monitoring-feedback:{digest[:24]}",
            feedback_version=FEEDBACK_VERSION,
            result_id=result_id,
            result_version=result_version,
            result_hash=result_hash,
            receipt_id=receipt_id,
            receipt_version=receipt_version,
            receipt_hash=receipt_hash,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_hash=calendar_hash,
            period_id=period_id,
            period_start_at=period_start_at,
            period_end_at=period_end_at,
            members=canonical_members,
            metric_facts=canonical_facts,
            observed_at=observed_at,
            available_at=available_at,
            valid_until=valid_until,
            evidence_ref=evidence_ref,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if self.feedback_version != FEEDBACK_VERSION:
            raise ValueError("Portfolio R8 feedback version is unsupported")
        for label, value in (
            ("feedback_id", self.feedback_id),
            ("result_id", self.result_id),
            ("result_version", self.result_version),
            ("receipt_id", self.receipt_id),
            ("receipt_version", self.receipt_version),
            ("calendar_id", self.calendar_id),
            ("calendar_version", self.calendar_version),
            ("period_id", self.period_id),
            ("evidence_ref", self.evidence_ref),
        ):
            _token(value, f"Portfolio R8 feedback {label}")
        for label, value in (
            ("result_hash", self.result_hash),
            ("receipt_hash", self.receipt_hash),
            ("calendar_hash", self.calendar_hash),
            ("content_hash", self.content_hash),
        ):
            _hash(value, f"Portfolio R8 feedback {label}")
        members = _canonical_members(self.members)
        facts = _canonical_facts(self.metric_facts, members)
        start = _aware(self.period_start_at, "Portfolio R8 period_start_at")
        end = _aware(self.period_end_at, "Portfolio R8 period_end_at")
        observed = _aware(self.observed_at, "Portfolio R8 feedback observed_at")
        available = _aware(self.available_at, "Portfolio R8 feedback available_at")
        valid_until = _aware(self.valid_until, "Portfolio R8 feedback valid_until")
        if start >= end or not start <= observed <= end:
            raise ValueError("Portfolio R8 feedback period/observation clocks differ")
        if available < observed or valid_until <= available:
            raise ValueError("Portfolio R8 feedback availability/validity clocks differ")
        expected_hash = _feedback_hash(
            result_id=self.result_id,
            result_version=self.result_version,
            result_hash=self.result_hash,
            receipt_id=self.receipt_id,
            receipt_version=self.receipt_version,
            receipt_hash=self.receipt_hash,
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            calendar_hash=self.calendar_hash,
            period_id=self.period_id,
            period_start_at=self.period_start_at,
            period_end_at=self.period_end_at,
            members=members,
            metric_facts=facts,
            observed_at=self.observed_at,
            available_at=self.available_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
        )
        if (
            self.feedback_id != f"portfolio-r8-monitoring-feedback:{expected_hash[:24]}"
            or self.content_hash != expected_hash
        ):
            raise ValueError("Portfolio R8 feedback identity or content seal differs")

    def validated_copy(self) -> PortfolioR8MonitoringFeedback:
        """Return a recursively reconstructed complete feedback graph."""

        if type(self) is not PortfolioR8MonitoringFeedback:
            raise TypeError("Portfolio R8 feedback type differs")
        copied = PortfolioR8MonitoringFeedback.create(
            result_id=self.result_id,
            result_version=self.result_version,
            result_hash=self.result_hash,
            receipt_id=self.receipt_id,
            receipt_version=self.receipt_version,
            receipt_hash=self.receipt_hash,
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            calendar_hash=self.calendar_hash,
            period_id=self.period_id,
            period_start_at=self.period_start_at,
            period_end_at=self.period_end_at,
            members=self.members,
            metric_facts=self.metric_facts,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
        )
        if copied != self:
            raise ValueError("Portfolio R8 feedback differs after replay")
        return copied


def _feedback_hash(
    *,
    result_id: str,
    result_version: str,
    result_hash: str,
    receipt_id: str,
    receipt_version: str,
    receipt_hash: str,
    calendar_id: str,
    calendar_version: str,
    calendar_hash: str,
    period_id: str,
    period_start_at: datetime,
    period_end_at: datetime,
    members: tuple[PortfolioR8MonitoringSourceMember, ...],
    metric_facts: tuple[PortfolioR8MonitoringRawRatio, ...],
    observed_at: datetime,
    available_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
) -> str:
    return canonical_hash(
        {
            "schema": FEEDBACK_VERSION,
            "result": (result_id, result_version, result_hash),
            "receipt": (receipt_id, receipt_version, receipt_hash),
            "calendar": (calendar_id, calendar_version, calendar_hash),
            "period": (period_id, period_start_at, period_end_at),
            "members": members,
            "metric_facts": metric_facts,
            "clocks": (observed_at, available_at, valid_until),
            "evidence_ref": evidence_ref,
        }
    )


@dataclass(frozen=True)
class PortfolioR8MonitoringFeedbackDefinition:
    """Complete raw feedback supplied by an independent Portfolio source."""

    definition_version: str
    feedback: PortfolioR8MonitoringFeedback
    content_hash: str = field(init=False)

    @classmethod
    def from_feedback(
        cls,
        feedback: PortfolioR8MonitoringFeedback,
    ) -> PortfolioR8MonitoringFeedbackDefinition:
        """Seal an exact raw feedback graph."""

        if type(feedback) is not PortfolioR8MonitoringFeedback:
            raise TypeError("Portfolio R8 feedback type differs")
        return cls(
            FEEDBACK_DEFINITION_VERSION,
            PortfolioR8MonitoringFeedback.validated_copy(feedback),
        )

    def __post_init__(self) -> None:
        if self.definition_version != FEEDBACK_DEFINITION_VERSION:
            raise ValueError("Portfolio R8 feedback definition version is unsupported")
        if type(self.feedback) is not PortfolioR8MonitoringFeedback:
            raise TypeError("Portfolio R8 feedback definition member type differs")
        feedback = PortfolioR8MonitoringFeedback.validated_copy(self.feedback)
        object.__setattr__(
            self,
            "content_hash",
            canonical_hash(
                {
                    "schema": FEEDBACK_DEFINITION_VERSION,
                    "feedback_id": feedback.feedback_id,
                    "feedback_version": feedback.feedback_version,
                    "feedback_hash": feedback.content_hash,
                }
            ),
        )

    def validated_copy(self) -> PortfolioR8MonitoringFeedbackDefinition:
        """Return a recursively rebuilt definition."""

        if type(self) is not PortfolioR8MonitoringFeedbackDefinition:
            raise TypeError("Portfolio R8 feedback definition type differs")
        copied = PortfolioR8MonitoringFeedbackDefinition.from_feedback(
            PortfolioR8MonitoringFeedback.validated_copy(self.feedback)
        )
        if copied != self:
            raise ValueError("Portfolio R8 feedback definition differs after replay")
        return copied


@dataclass(frozen=True)
class PortfolioR8MonitoringFeedbackSourceReceipt:
    """Independent Portfolio receipt binding one raw feedback definition."""

    source_receipt_id: str
    source_receipt_version: str
    source_owner: str
    feedback_id: str
    feedback_version: str
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
        feedback_id: str,
        feedback_version: str,
        definition_hash: str,
        available_at: datetime,
        valid_until: datetime,
        evidence_ref: str,
    ) -> PortfolioR8MonitoringFeedbackSourceReceipt:
        """Create a content-addressed receipt without metric values."""

        values = (
            source_receipt_id,
            source_receipt_version,
            "portfolio",
            feedback_id,
            feedback_version,
            definition_hash,
            available_at,
            valid_until,
            evidence_ref,
        )
        return cls(*values, _feedback_source_hash(*values))

    def __post_init__(self) -> None:
        for label, value in (
            ("source_receipt_id", self.source_receipt_id),
            ("source_receipt_version", self.source_receipt_version),
            ("source_owner", self.source_owner),
            ("feedback_id", self.feedback_id),
            ("feedback_version", self.feedback_version),
            ("evidence_ref", self.evidence_ref),
        ):
            _token(value, f"Portfolio R8 feedback source {label}")
        if self.source_receipt_version != FEEDBACK_SOURCE_RECEIPT_VERSION:
            raise ValueError("Portfolio R8 feedback source version is unsupported")
        if self.source_owner != "portfolio":
            raise ValueError("Portfolio R8 feedback source owner differs")
        _hash(self.definition_hash, "Portfolio R8 feedback source definition_hash")
        _hash(self.content_hash, "Portfolio R8 feedback source content_hash")
        _aware(self.available_at, "Portfolio R8 feedback source available_at")
        _aware(self.valid_until, "Portfolio R8 feedback source valid_until")
        if self.available_at >= self.valid_until:
            raise ValueError("Portfolio R8 feedback source validity is empty")
        if self.content_hash != _feedback_source_hash(
            self.source_receipt_id,
            self.source_receipt_version,
            self.source_owner,
            self.feedback_id,
            self.feedback_version,
            self.definition_hash,
            self.available_at,
            self.valid_until,
            self.evidence_ref,
        ):
            raise ValueError("Portfolio R8 feedback source hash differs")

    def validated_copy(self) -> PortfolioR8MonitoringFeedbackSourceReceipt:
        """Return an exact class-bound receipt reconstruction."""

        if type(self) is not PortfolioR8MonitoringFeedbackSourceReceipt:
            raise TypeError("Portfolio R8 feedback source receipt type differs")
        copied = PortfolioR8MonitoringFeedbackSourceReceipt.create(
            source_receipt_id=self.source_receipt_id,
            source_receipt_version=self.source_receipt_version,
            feedback_id=self.feedback_id,
            feedback_version=self.feedback_version,
            definition_hash=self.definition_hash,
            available_at=self.available_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
        )
        if copied != self:
            raise ValueError("Portfolio R8 feedback source differs after replay")
        return copied


def _feedback_source_hash(
    source_receipt_id: str,
    source_receipt_version: str,
    source_owner: str,
    feedback_id: str,
    feedback_version: str,
    definition_hash: str,
    available_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
) -> str:
    return canonical_hash(
        {
            "schema": FEEDBACK_SOURCE_RECEIPT_VERSION,
            "source": (source_receipt_id, source_receipt_version, source_owner),
            "feedback": (feedback_id, feedback_version, definition_hash),
            "window": (available_at, valid_until),
            "evidence_ref": evidence_ref,
        }
    )


__all__ = [
    "FEEDBACK_DEFINITION_VERSION",
    "FEEDBACK_SOURCE_RECEIPT_VERSION",
    "FEEDBACK_VERSION",
    "PortfolioR8MonitoringFeedback",
    "PortfolioR8MonitoringFeedbackDefinition",
    "PortfolioR8MonitoringFeedbackSourceReceipt",
    "PortfolioR8MonitoringMemberKind",
    "PortfolioR8MonitoringRawRatio",
    "PortfolioR8MonitoringSourceMember",
]
