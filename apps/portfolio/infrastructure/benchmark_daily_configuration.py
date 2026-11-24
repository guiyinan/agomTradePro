"""Restore current Portfolio planning and benchmark methodology heads and all five pinned bodies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from apps.portfolio.domain.benchmark_execution_approval import BenchmarkArtifactRef
from apps.portfolio.domain.policy_benchmark_corporate_action import (
    PolicyBenchmarkCorporateActionSourceRef,
    PortfolioPolicyBenchmarkCorporateAction,
)
from apps.portfolio.domain.policy_benchmark_cost_tax import (
    PolicyBenchmarkCostTaxRule,
    PortfolioPolicyBenchmarkCostTax,
)
from apps.portfolio.domain.policy_benchmark_daily_valuation import BenchmarkDayUnavailable
from apps.portfolio.domain.policy_benchmark_definition import PortfolioPolicyBenchmarkDefinition
from apps.portfolio.domain.policy_benchmark_fx_fixing import PortfolioPolicyBenchmarkFxFixing
from apps.portfolio.domain.policy_benchmark_price_fixing import PortfolioPolicyBenchmarkPriceFixing
from apps.portfolio.domain.policy_benchmark_trading_calendar import (
    PortfolioPolicyBenchmarkTradingCalendar,
)
from apps.portfolio.infrastructure.planning_policy_activation_models import (
    PortfolioPlanningPolicyActivationModel,
)
from apps.portfolio.infrastructure.planning_policy_activation_repository import (
    DjangoPlanningPolicyActivationRepository,
)
from apps.portfolio.infrastructure.planning_policy_definition_repository import (
    DjangoPlanningPolicyDefinitionRepository,
)
from apps.portfolio.infrastructure.policy_benchmark_corporate_action_repository import (
    DjangoPolicyBenchmarkCorporateActionRepository,
)
from apps.portfolio.infrastructure.policy_benchmark_cost_tax_repository import (
    DjangoPolicyBenchmarkCostTaxRepository,
)
from apps.portfolio.infrastructure.policy_benchmark_definition_repository import (
    DjangoPolicyBenchmarkDefinitionRepository,
)
from apps.portfolio.infrastructure.policy_benchmark_fx_fixing_repository import (
    DjangoPolicyBenchmarkFxFixingRepository,
)
from apps.portfolio.infrastructure.policy_benchmark_methodology_activation_models import (
    PortfolioPolicyBenchmarkMethodologyActivationModel,
)
from apps.portfolio.infrastructure.policy_benchmark_methodology_activation_repository import (
    DjangoPolicyBenchmarkMethodologyActivationRepository,
)
from apps.portfolio.infrastructure.policy_benchmark_price_fixing_repository import (
    DjangoPolicyBenchmarkPriceFixingRepository,
)
from apps.portfolio.infrastructure.policy_benchmark_trading_calendar_repository import (
    DjangoPolicyBenchmarkTradingCalendarRepository,
)


@dataclass(frozen=True, slots=True)
class DailyConfiguration:
    definition: PortfolioPolicyBenchmarkDefinition
    calendar: PortfolioPolicyBenchmarkTradingCalendar
    price: PortfolioPolicyBenchmarkPriceFixing
    action_source: PolicyBenchmarkCorporateActionSourceRef
    trade_charge: PolicyBenchmarkCostTaxRule
    method_ref: BenchmarkArtifactRef
    policy_ref: BenchmarkArtifactRef
    planning_ref: BenchmarkArtifactRef
    valid_until: datetime


def read_daily_configuration(
    *, definition_id: str, policy_id: str, at: datetime, using: str
) -> DailyConfiguration:
    """Fence both logical heads and materialize immutable constituent definitions from owner ledgers."""
    methods = DjangoPolicyBenchmarkMethodologyActivationRepository(using=using)
    planning = DjangoPlanningPolicyActivationRepository(using=using)
    method = methods.get_current_head(definition_id=definition_id, as_of=at)
    plan = planning.get_current_head(policy_id=policy_id, as_of=at)
    if method is None or plan is None:
        raise BenchmarkDayUnavailable("missing active planning or benchmark configuration")
    # Both existing successor writers lock their structural predecessor before append.
    if (
        not PortfolioPolicyBenchmarkMethodologyActivationModel.objects.using(using)
        .select_for_update()
        .filter(content_hash=method.content_hash)
        .exists()
        or not PortfolioPlanningPolicyActivationModel._default_manager.using(using)
        .select_for_update()
        .filter(content_hash=plan.content_hash)
        .exists()
    ):
        raise BenchmarkDayUnavailable("configuration head disappeared")
    if (
        methods.get_current_head(definition_id=definition_id, as_of=at) != method
        or planning.get_current_head(policy_id=policy_id, as_of=at) != plan
    ):
        raise BenchmarkDayUnavailable("benchmark configuration head changed")
    d = method.subject
    definition = DjangoPolicyBenchmarkDefinitionRepository(using=using).get_exact(
        definition_id=d.definition_id,
        definition_version=d.definition_version,
        expected_content_hash=d.definition_content_hash,
        as_of=at,
    )
    ps = plan.subject
    policy = DjangoPlanningPolicyDefinitionRepository(using=using).get_exact(
        policy_id=ps.policy_id,
        policy_version=ps.policy_version,
        expected_content_hash=ps.definition_content_hash,
        as_of=at,
    )
    if (
        definition is None
        or policy is None
        or definition.identity_hash != d.definition_identity_hash
        or policy.identity_hash != ps.definition_identity_hash
    ):
        raise BenchmarkDayUnavailable("pinned policy or benchmark definition missing")
    refs = (
        definition.corporate_action_ref,
        definition.cost_tax_ref,
        definition.fx_fixing_ref,
        definition.price_fixing_ref,
        definition.trading_calendar_ref,
    )
    if d.bundle.methodology_refs != refs:
        raise BenchmarkDayUnavailable("methodology activation and definition disagree")
    repositories: tuple[
        DjangoPolicyBenchmarkCorporateActionRepository
        | DjangoPolicyBenchmarkCostTaxRepository
        | DjangoPolicyBenchmarkFxFixingRepository
        | DjangoPolicyBenchmarkPriceFixingRepository
        | DjangoPolicyBenchmarkTradingCalendarRepository,
        ...,
    ] = (
        DjangoPolicyBenchmarkCorporateActionRepository(using=using),
        DjangoPolicyBenchmarkCostTaxRepository(using=using),
        DjangoPolicyBenchmarkFxFixingRepository(using=using),
        DjangoPolicyBenchmarkPriceFixingRepository(using=using),
        DjangoPolicyBenchmarkTradingCalendarRepository(using=using),
    )
    bodies = []
    for ref, repo in zip(refs, repositories, strict=True):
        body = repo.get_exact(
            methodology_id=ref.artifact_id,
            methodology_version=ref.artifact_version,
            expected_content_hash=ref.content_hash,
            as_of=at,
        )
        if body is None or (body.owner, body.artifact_type, body.recorded_at, body.valid_until) != (
            ref.owner,
            ref.artifact_type,
            ref.recorded_at,
            ref.valid_until,
        ):
            raise BenchmarkDayUnavailable("missing or substituted benchmark method")
        bodies.append(body)
    price, calendar = bodies[3], bodies[4]
    if not isinstance(price, PortfolioPolicyBenchmarkPriceFixing) or not isinstance(
        calendar, PortfolioPolicyBenchmarkTradingCalendar
    ):
        raise BenchmarkDayUnavailable("invalid benchmark fixing/calendar")
    if (
        price.price_field != "close"
        or price.adjustment_basis != "unadjusted"
        or len(price.source_priority) != 1
        or (price.source_priority[0].owner, price.source_priority[0].artifact_id)
        != ("data_center", "equity.price.bar.current")
    ):
        raise BenchmarkDayUnavailable(
            "benchmark requires an unambiguous Data Center unadjusted closing fixing"
        )
    corporate, costs, fx = bodies[0], bodies[1], bodies[2]
    if (
        not isinstance(corporate, PortfolioPolicyBenchmarkCorporateAction)
        or not isinstance(costs, PortfolioPolicyBenchmarkCostTax)
        or not isinstance(fx, PortfolioPolicyBenchmarkFxFixing)
    ):
        raise BenchmarkDayUnavailable("invalid corporate-action, charge or FX methodology")
    constituents = definition.constituents
    if (
        len(constituents) != 1
        or constituents[0].weight != Decimal(1)
        or constituents[0].currency != definition.base_currency
        or definition.base_currency != "CNY"
        or policy.slippage_rate != 0
        or policy.max_asset_weight != 1
    ):
        raise BenchmarkDayUnavailable(
            "benchmark requires an approved single fully invested CNY proxy with zero modeled slippage"
        )
    if (
        corporate.price_input_adjustment_basis != "unadjusted"
        or corporate.missing_action_policy != "fail_closed"
        or fx.missing_fx_policy != "fail_closed"
    ):
        raise BenchmarkDayUnavailable("unsupported event coverage or FX methodology")
    trade_rules = [r for r in costs.charge_rules if r.charge_event == "trade"]
    if len(trade_rules) != 1:
        raise BenchmarkDayUnavailable(
            "valuation requires one precisely applicable stock trade charge"
        )
    fee = trade_rules[0]
    if (
        fee.asset_scope_code,
        fee.jurisdiction_code,
        fee.charge_kind,
        fee.trade_side,
        fee.calculation_basis,
        fee.recognition_timing,
        fee.calculation_mode,
        fee.charge_currency,
        fee.rounding_mode,
    ) != (
        "CN-EQUITY",
        "CN",
        "fee",
        "both",
        "gross_trade_notional",
        "trade_execution",
        "rate",
        "CNY",
        "half_up",
    ) or fee.rate != policy.fee_rate:
        raise BenchmarkDayUnavailable(
            "unknown or different benchmark and planning commission terms"
        )
    deadlines = [
        ref.valid_until for body in (price, corporate, costs, fx) for ref in body.source_priority
    ]
    if any(
        ref.recorded_at > at
        for body in (price, corporate, costs, fx)
        for ref in body.source_priority
    ):
        raise BenchmarkDayUnavailable("one or more governed method sources are not yet known")
    return DailyConfiguration(
        definition,
        calendar,
        price,
        corporate.source_priority[0],
        fee,
        BenchmarkArtifactRef(method.activation_id, method.activation_version, method.content_hash),
        BenchmarkArtifactRef(policy.policy_id, policy.policy_version, policy.content_hash),
        BenchmarkArtifactRef(plan.activation_id, plan.activation_version, plan.content_hash),
        min(
            method.valid_until,
            plan.valid_until,
            policy.valid_until,
            definition.valid_until,
            *(r.valid_until for r in refs),
            *deadlines,
        ),
    )
