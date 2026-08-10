"""Independent Portfolio facts for R5 post-promotion monitoring."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal

from apps.fixed_income.domain.evidence import canonical_hash, decimal_text
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringCalendar,
    R5MonitoringMetric,
    R5MonitoringMetricKey,
    R5MonitoringPeriodEntry,
    R5MonitoringTarget,
    _require_aware,
    _require_decimal,
    _require_hash,
    _require_int,
    _require_token,
)
from apps.research.domain.r5_relative_value_monitoring_owners import (
    R5MonitoringOwnerRef,
    R5MonitoringOwnerRole,
)

MAX_RAW_COUNT = 1_000_000_000


def _require_rate(value: object, label: str, *, lower: str, upper: str) -> Decimal:
    decimal = _require_decimal(value, label)
    if not Decimal(lower) <= decimal <= Decimal(upper):
        raise ValueError(f"{label} is outside its governed domain")
    return decimal


@dataclass(frozen=True)
class R5MonitoringPortfolioSourceProjection:
    """Sealed raw Portfolio projection from which all seven metrics derive."""

    owner_record: R5MonitoringOwnerRef
    source_observed_at: datetime
    coverage_observed_count: int
    coverage_expected_count: int
    target_gross_return: Decimal
    benchmark_gross_return: Decimal
    target_execution_cost: Decimal
    target_financing_cost: Decimal
    target_liquidity_cost: Decimal
    benchmark_execution_cost: Decimal
    benchmark_financing_cost: Decimal
    benchmark_liquidity_cost: Decimal
    target_drawdown: Decimal
    benchmark_drawdown: Decimal
    liquidity_breach_count: int
    liquidity_eligible_count: int
    capacity_used: Decimal
    capacity_limit: Decimal
    realized_credit_loss: Decimal
    credit_exposure: Decimal
    content_hash: str = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        owner_record: R5MonitoringOwnerRef,
        source_observed_at: datetime,
        coverage_observed_count: int,
        coverage_expected_count: int,
        target_gross_return: Decimal,
        benchmark_gross_return: Decimal,
        target_execution_cost: Decimal,
        target_financing_cost: Decimal,
        target_liquidity_cost: Decimal,
        benchmark_execution_cost: Decimal,
        benchmark_financing_cost: Decimal,
        benchmark_liquidity_cost: Decimal,
        target_drawdown: Decimal,
        benchmark_drawdown: Decimal,
        liquidity_breach_count: int,
        liquidity_eligible_count: int,
        capacity_used: Decimal,
        capacity_limit: Decimal,
        realized_credit_loss: Decimal,
        credit_exposure: Decimal,
    ) -> R5MonitoringPortfolioSourceProjection:
        """Create one content-addressed raw owner projection."""

        return cls(
            owner_record=owner_record,
            source_observed_at=source_observed_at,
            coverage_observed_count=coverage_observed_count,
            coverage_expected_count=coverage_expected_count,
            target_gross_return=target_gross_return,
            benchmark_gross_return=benchmark_gross_return,
            target_execution_cost=target_execution_cost,
            target_financing_cost=target_financing_cost,
            target_liquidity_cost=target_liquidity_cost,
            benchmark_execution_cost=benchmark_execution_cost,
            benchmark_financing_cost=benchmark_financing_cost,
            benchmark_liquidity_cost=benchmark_liquidity_cost,
            target_drawdown=target_drawdown,
            benchmark_drawdown=benchmark_drawdown,
            liquidity_breach_count=liquidity_breach_count,
            liquidity_eligible_count=liquidity_eligible_count,
            capacity_used=capacity_used,
            capacity_limit=capacity_limit,
            realized_credit_loss=realized_credit_loss,
            credit_exposure=credit_exposure,
        )

    def __post_init__(self) -> None:
        if (
            type(self.owner_record) is not R5MonitoringOwnerRef
            or self.owner_record.role is not R5MonitoringOwnerRole.PORTFOLIO_MONITORING_SOURCE
        ):
            raise ValueError("source projection requires the canonical Portfolio owner role")
        self.owner_record.__post_init__()
        _require_aware(self.source_observed_at, "source projection observed_at")
        if not self.source_observed_at <= self.owner_record.known_at:
            raise ValueError("source projection knowledge clocks are invalid")
        _require_int(
            self.coverage_observed_count,
            "source projection coverage observed count",
            minimum=0,
            maximum=MAX_RAW_COUNT,
        )
        _require_int(
            self.coverage_expected_count,
            "source projection coverage expected count",
            minimum=1,
            maximum=MAX_RAW_COUNT,
        )
        if self.coverage_observed_count > self.coverage_expected_count:
            raise ValueError("source projection coverage numerator exceeds denominator")
        for label, value in (
            ("target gross return", self.target_gross_return),
            ("benchmark gross return", self.benchmark_gross_return),
        ):
            _require_rate(value, f"source projection {label}", lower="-1", upper="2")
        target_cost = self._validated_cost(
            "target",
            self.target_execution_cost,
            self.target_financing_cost,
            self.target_liquidity_cost,
        )
        self._validated_cost(
            "benchmark",
            self.benchmark_execution_cost,
            self.benchmark_financing_cost,
            self.benchmark_liquidity_cost,
        )
        if target_cost > Decimal("1"):
            raise ValueError("source projection total target cost exceeds one")
        _require_rate(
            self.target_drawdown,
            "source projection target drawdown",
            lower="0",
            upper="1",
        )
        _require_rate(
            self.benchmark_drawdown,
            "source projection benchmark drawdown",
            lower="0",
            upper="1",
        )
        _require_int(
            self.liquidity_breach_count,
            "source projection liquidity breach count",
            minimum=0,
            maximum=MAX_RAW_COUNT,
        )
        _require_int(
            self.liquidity_eligible_count,
            "source projection liquidity eligible count",
            minimum=1,
            maximum=MAX_RAW_COUNT,
        )
        if self.liquidity_breach_count > self.liquidity_eligible_count:
            raise ValueError("source projection liquidity numerator exceeds denominator")
        capacity_used = _require_decimal(self.capacity_used, "source projection capacity used")
        capacity_limit = _require_decimal(self.capacity_limit, "source projection capacity limit")
        if not Decimal("0") <= capacity_used <= capacity_limit or capacity_limit <= 0:
            raise ValueError("source projection capacity numerator or denominator is invalid")
        credit_loss = _require_decimal(
            self.realized_credit_loss, "source projection realized credit loss"
        )
        credit_exposure = _require_decimal(
            self.credit_exposure, "source projection credit exposure"
        )
        if not Decimal("0") <= credit_loss <= credit_exposure or credit_exposure <= 0:
            raise ValueError("source projection credit numerator or denominator is invalid")
        self.derive_metrics()
        object.__setattr__(self, "content_hash", portfolio_source_projection_hash(self))

    @staticmethod
    def _validated_cost(label: str, *components: Decimal) -> Decimal:
        total = Decimal("0")
        for component in components:
            total += _require_rate(
                component,
                f"source projection {label} cost component",
                lower="0",
                upper="1",
            )
        if total > Decimal("1"):
            raise ValueError(f"source projection total {label} cost exceeds one")
        return total

    def derive_metrics(self) -> tuple[R5MonitoringMetric, ...]:
        """Derive all canonical values from sealed raw numerators and denominators."""

        target_cost = sum(
            (
                self.target_execution_cost,
                self.target_financing_cost,
                self.target_liquidity_cost,
            ),
            Decimal("0"),
        )
        benchmark_cost = sum(
            (
                self.benchmark_execution_cost,
                self.benchmark_financing_cost,
                self.benchmark_liquidity_cost,
            ),
            Decimal("0"),
        )
        values = {
            R5MonitoringMetricKey.COVERAGE_RATIO: (
                Decimal(self.coverage_observed_count) / Decimal(self.coverage_expected_count)
            ),
            R5MonitoringMetricKey.EXCESS_NET_RETURN: (
                self.target_gross_return
                - target_cost
                - self.benchmark_gross_return
                + benchmark_cost
            ),
            R5MonitoringMetricKey.DRAWDOWN_INCREASE: (
                self.target_drawdown - self.benchmark_drawdown
            ),
            R5MonitoringMetricKey.TOTAL_TARGET_COST: target_cost,
            R5MonitoringMetricKey.LIQUIDITY_BREACH: (
                Decimal(self.liquidity_breach_count) / Decimal(self.liquidity_eligible_count)
            ),
            R5MonitoringMetricKey.PEAK_CAPACITY_UTILIZATION: (
                self.capacity_used / self.capacity_limit
            ),
            R5MonitoringMetricKey.REALIZED_CREDIT_LOSS: (
                self.realized_credit_loss / self.credit_exposure
            ),
        }
        return tuple(
            R5MonitoringMetric.canonical(key, values[key]) for key in R5MonitoringMetricKey
        )

    def validated_copy(self) -> R5MonitoringPortfolioSourceProjection:
        """Rebuild the full raw projection and compare its live seal."""

        rebuilt = R5MonitoringPortfolioSourceProjection.create(
            owner_record=self.owner_record.validated_copy(),
            source_observed_at=self.source_observed_at,
            coverage_observed_count=self.coverage_observed_count,
            coverage_expected_count=self.coverage_expected_count,
            target_gross_return=self.target_gross_return,
            benchmark_gross_return=self.benchmark_gross_return,
            target_execution_cost=self.target_execution_cost,
            target_financing_cost=self.target_financing_cost,
            target_liquidity_cost=self.target_liquidity_cost,
            benchmark_execution_cost=self.benchmark_execution_cost,
            benchmark_financing_cost=self.benchmark_financing_cost,
            benchmark_liquidity_cost=self.benchmark_liquidity_cost,
            target_drawdown=self.target_drawdown,
            benchmark_drawdown=self.benchmark_drawdown,
            liquidity_breach_count=self.liquidity_breach_count,
            liquidity_eligible_count=self.liquidity_eligible_count,
            capacity_used=self.capacity_used,
            capacity_limit=self.capacity_limit,
            realized_credit_loss=self.realized_credit_loss,
            credit_exposure=self.credit_exposure,
        )
        if rebuilt != self:
            raise ValueError("source projection live seal differs")
        return rebuilt


def portfolio_source_projection_hash(value: R5MonitoringPortfolioSourceProjection) -> str:
    """Recompute the raw Portfolio source-projection seal."""

    decimals = (
        value.target_gross_return,
        value.benchmark_gross_return,
        value.target_execution_cost,
        value.target_financing_cost,
        value.target_liquidity_cost,
        value.benchmark_execution_cost,
        value.benchmark_financing_cost,
        value.benchmark_liquidity_cost,
        value.target_drawdown,
        value.benchmark_drawdown,
        value.capacity_used,
        value.capacity_limit,
        value.realized_credit_loss,
        value.credit_exposure,
    )
    return canonical_hash(
        {
            "schema": "portfolio-r5-monitoring-source-projection.v1",
            "owner_record": value.owner_record,
            "source_observed_at": value.source_observed_at,
            "counts": (
                value.coverage_observed_count,
                value.coverage_expected_count,
                value.liquidity_breach_count,
                value.liquidity_eligible_count,
            ),
            "decimal_values": tuple(decimal_text(item) for item in decimals),
        }
    )


@dataclass(frozen=True)
class R5PostPromotionMonitoringFact:
    """Independent Portfolio monitoring fact for one exact period."""

    fact_id: str
    fact_version: str
    period_id: str
    period_start: datetime
    period_end: datetime
    calendar_id: str
    calendar_version: str
    calendar_hash: str
    policy_id: str
    policy_version: str
    policy_hash: str
    target_hash: str
    scope_id: str
    scope_hash: str
    decision_id: str
    decision_version: str
    decision_hash: str
    lifecycle_hash: str
    fixed_income_result_id: str
    fixed_income_result_version: str
    fixed_income_result_hash: str
    fixed_income_owner_seal_id: str
    fixed_income_owner_seal_version: str
    fixed_income_owner_seal_hash: str
    benchmark_owner: str
    benchmark_id: str
    benchmark_version: str
    benchmark_hash: str
    cost_policy_owner: str
    cost_policy_id: str
    cost_policy_version: str
    cost_policy_hash: str
    liquidity_policy_owner: str
    liquidity_policy_id: str
    liquidity_policy_version: str
    liquidity_policy_hash: str
    source_projection: R5MonitoringPortfolioSourceProjection
    observed_at: datetime
    available_at: datetime
    recorded_at: datetime
    valid_until: datetime
    observed_label_hash: str
    observed_data_schema_hash: str
    research_only: bool
    must_not_publish_current: bool
    must_not_decide: bool
    must_not_execute: bool
    content_hash: str
    metrics: tuple[R5MonitoringMetric, ...] = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        fact_id: str,
        fact_version: str,
        period: R5MonitoringPeriodEntry,
        calendar: R5MonitoringCalendar,
        target: R5MonitoringTarget,
        policy_id: str,
        policy_version: str,
        policy_hash: str,
        source_projection: R5MonitoringPortfolioSourceProjection,
        observed_at: datetime,
        available_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        observed_label_hash: str,
        observed_data_schema_hash: str,
    ) -> R5PostPromotionMonitoringFact:
        """Seal raw owner inputs; metric values are never accepted from callers."""

        if type(period) is not R5MonitoringPeriodEntry:
            raise TypeError("monitoring fact period type is invalid")
        period.__post_init__()
        if type(calendar) is not R5MonitoringCalendar or calendar.validated_copy() != calendar:
            raise ValueError("monitoring fact calendar projection differs")
        if type(target) is not R5MonitoringTarget or target.validated_copy() != target:
            raise ValueError("monitoring fact target projection differs")
        if type(source_projection) is not R5MonitoringPortfolioSourceProjection:
            raise TypeError("monitoring fact source projection type is invalid")
        source = source_projection.validated_copy()
        values = _fact_values(
            fact_id=fact_id,
            fact_version=fact_version,
            period=period,
            calendar=calendar,
            target=target,
            policy_id=policy_id,
            policy_version=policy_version,
            policy_hash=policy_hash,
            source_projection=source,
            observed_at=observed_at,
            available_at=available_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            observed_label_hash=observed_label_hash,
            observed_data_schema_hash=observed_data_schema_hash,
        )
        digest = canonical_hash(
            {"schema": "portfolio-r5-post-promotion-monitoring-fact.v2", "fields": values}
        )
        return cls(
            fact_id=fact_id,
            fact_version=fact_version,
            period_id=period.period_id,
            period_start=period.period_start,
            period_end=period.period_end,
            calendar_id=calendar.owner.owner_id,
            calendar_version=calendar.owner.owner_version,
            calendar_hash=calendar.content_hash,
            policy_id=policy_id,
            policy_version=policy_version,
            policy_hash=policy_hash,
            target_hash=target.content_hash,
            scope_id=target.active_lifecycle.scope_id,
            scope_hash=target.active_lifecycle.scope_hash,
            decision_id=target.active_lifecycle.decision_id,
            decision_version=target.active_lifecycle.decision_version,
            decision_hash=target.active_lifecycle.decision_hash,
            lifecycle_hash=target.active_lifecycle.content_hash,
            fixed_income_result_id=target.fixed_income.result_id,
            fixed_income_result_version=target.fixed_income.result_version,
            fixed_income_result_hash=target.fixed_income.result_hash,
            fixed_income_owner_seal_id=target.fixed_income.owner_seal_id,
            fixed_income_owner_seal_version=target.fixed_income.owner_seal_version,
            fixed_income_owner_seal_hash=target.fixed_income.owner_seal_hash,
            benchmark_owner=target.benchmark.owner,
            benchmark_id=target.benchmark.owner_id,
            benchmark_version=target.benchmark.owner_version,
            benchmark_hash=target.benchmark.content_hash,
            cost_policy_owner=target.cost_policy.owner,
            cost_policy_id=target.cost_policy.owner_id,
            cost_policy_version=target.cost_policy.owner_version,
            cost_policy_hash=target.cost_policy.content_hash,
            liquidity_policy_owner=target.liquidity_policy.owner,
            liquidity_policy_id=target.liquidity_policy.owner_id,
            liquidity_policy_version=target.liquidity_policy.owner_version,
            liquidity_policy_hash=target.liquidity_policy.content_hash,
            source_projection=source,
            observed_at=observed_at,
            available_at=available_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            observed_label_hash=observed_label_hash,
            observed_data_schema_hash=observed_data_schema_hash,
            research_only=True,
            must_not_publish_current=True,
            must_not_decide=True,
            must_not_execute=True,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        for label in (
            "fact_id",
            "fact_version",
            "calendar_id",
            "calendar_version",
            "policy_id",
            "policy_version",
            "scope_id",
            "decision_id",
            "decision_version",
            "fixed_income_result_id",
            "fixed_income_result_version",
            "fixed_income_owner_seal_id",
            "fixed_income_owner_seal_version",
            "benchmark_owner",
            "benchmark_id",
            "benchmark_version",
            "cost_policy_owner",
            "cost_policy_id",
            "cost_policy_version",
            "liquidity_policy_owner",
            "liquidity_policy_id",
            "liquidity_policy_version",
        ):
            _require_token(getattr(self, label), f"monitoring fact {label}")
        for label in (
            "period_id",
            "calendar_hash",
            "policy_hash",
            "target_hash",
            "scope_hash",
            "decision_hash",
            "lifecycle_hash",
            "fixed_income_result_hash",
            "fixed_income_owner_seal_hash",
            "benchmark_hash",
            "cost_policy_hash",
            "liquidity_policy_hash",
            "observed_label_hash",
            "observed_data_schema_hash",
            "content_hash",
        ):
            _require_hash(getattr(self, label), f"monitoring fact {label}")
        if type(self.source_projection) is not R5MonitoringPortfolioSourceProjection:
            raise TypeError("monitoring fact source projection type is invalid")
        source = self.source_projection.validated_copy()
        if source != self.source_projection:
            raise ValueError("monitoring fact source projection differs")
        for label in (
            "period_start",
            "period_end",
            "observed_at",
            "available_at",
            "recorded_at",
            "valid_until",
        ):
            _require_aware(getattr(self, label), f"monitoring fact {label}")
        if not (
            self.period_start
            < self.period_end
            <= self.observed_at
            <= self.available_at
            <= self.recorded_at
            < self.valid_until
            <= source.owner_record.valid_until
        ):
            raise ValueError("monitoring fact clocks are invalid")
        if not (
            source.source_observed_at <= self.period_end
            and source.owner_record.recorded_at <= self.observed_at
        ):
            raise ValueError("monitoring fact source clocks exceed the governed period")
        expected_period = R5MonitoringPeriodEntry.create(
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            period_start=self.period_start,
            period_end=self.period_end,
        )
        if self.period_id != expected_period.period_id:
            raise ValueError("monitoring fact period identity differs")
        object.__setattr__(self, "metrics", source.derive_metrics())
        if not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_decide
            and self.must_not_execute
        ):
            raise ValueError("monitoring fact safety boundary differs")
        if self.content_hash != monitoring_fact_hash(self):
            raise ValueError("monitoring fact content seal differs")

    def validated_copy(self) -> R5PostPromotionMonitoringFact:
        """Rebuild every fact field, raw owner input, and derived metric."""

        rebuilt = replace(
            self,
            source_projection=self.source_projection.validated_copy(),
        )
        if rebuilt != self:
            raise ValueError("monitoring fact validated copy differs")
        return rebuilt


def _fact_values(
    *,
    fact_id: str,
    fact_version: str,
    period: R5MonitoringPeriodEntry,
    calendar: R5MonitoringCalendar,
    target: R5MonitoringTarget,
    policy_id: str,
    policy_version: str,
    policy_hash: str,
    source_projection: R5MonitoringPortfolioSourceProjection,
    observed_at: datetime,
    available_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
    observed_label_hash: str,
    observed_data_schema_hash: str,
) -> tuple[object, ...]:
    return (
        fact_id,
        fact_version,
        period.period_id,
        period.period_start,
        period.period_end,
        calendar.owner.owner_id,
        calendar.owner.owner_version,
        calendar.content_hash,
        policy_id,
        policy_version,
        policy_hash,
        target.content_hash,
        target.active_lifecycle.scope_id,
        target.active_lifecycle.scope_hash,
        target.active_lifecycle.decision_id,
        target.active_lifecycle.decision_version,
        target.active_lifecycle.decision_hash,
        target.active_lifecycle.content_hash,
        target.fixed_income.result_id,
        target.fixed_income.result_version,
        target.fixed_income.result_hash,
        target.fixed_income.owner_seal_id,
        target.fixed_income.owner_seal_version,
        target.fixed_income.owner_seal_hash,
        target.benchmark.owner,
        target.benchmark.owner_id,
        target.benchmark.owner_version,
        target.benchmark.content_hash,
        target.cost_policy.owner,
        target.cost_policy.owner_id,
        target.cost_policy.owner_version,
        target.cost_policy.content_hash,
        target.liquidity_policy.owner,
        target.liquidity_policy.owner_id,
        target.liquidity_policy.owner_version,
        target.liquidity_policy.content_hash,
        source_projection,
        observed_at,
        available_at,
        recorded_at,
        valid_until,
        observed_label_hash,
        observed_data_schema_hash,
        source_projection.derive_metrics(),
        True,
        True,
        True,
        True,
    )


def monitoring_fact_hash(value: R5PostPromotionMonitoringFact) -> str:
    """Recompute the independent Portfolio monitoring fact seal."""

    return canonical_hash(
        {
            "schema": "portfolio-r5-post-promotion-monitoring-fact.v2",
            "fields": (
                value.fact_id,
                value.fact_version,
                value.period_id,
                value.period_start,
                value.period_end,
                value.calendar_id,
                value.calendar_version,
                value.calendar_hash,
                value.policy_id,
                value.policy_version,
                value.policy_hash,
                value.target_hash,
                value.scope_id,
                value.scope_hash,
                value.decision_id,
                value.decision_version,
                value.decision_hash,
                value.lifecycle_hash,
                value.fixed_income_result_id,
                value.fixed_income_result_version,
                value.fixed_income_result_hash,
                value.fixed_income_owner_seal_id,
                value.fixed_income_owner_seal_version,
                value.fixed_income_owner_seal_hash,
                value.benchmark_owner,
                value.benchmark_id,
                value.benchmark_version,
                value.benchmark_hash,
                value.cost_policy_owner,
                value.cost_policy_id,
                value.cost_policy_version,
                value.cost_policy_hash,
                value.liquidity_policy_owner,
                value.liquidity_policy_id,
                value.liquidity_policy_version,
                value.liquidity_policy_hash,
                value.source_projection,
                value.observed_at,
                value.available_at,
                value.recorded_at,
                value.valid_until,
                value.observed_label_hash,
                value.observed_data_schema_hash,
                value.metrics,
                value.research_only,
                value.must_not_publish_current,
                value.must_not_decide,
                value.must_not_execute,
            ),
        }
    )


__all__ = [
    "R5MonitoringPortfolioSourceProjection",
    "R5PostPromotionMonitoringFact",
    "monitoring_fact_hash",
    "portfolio_source_projection_hash",
]
