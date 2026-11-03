"""High-value fail-closed combinations across portfolio risk domain rules."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.risk_center.domain.portfolio_baseline_risk import (
    assess_portfolio_baseline,
    intersect_native_account_limits,
    resolve_portfolio_baseline_parameters,
)
from apps.risk_center.domain.portfolio_capacity import CapacityValue
from apps.risk_center.domain.portfolio_exposure import (
    ETFConstituent,
    ETFConstituentKind,
    ETFConstituentReport,
    ExposureOutcome,
    PortfolioAssetKind,
    PortfolioRiskAsset,
    assess_portfolio_industry_exposure,
)
from apps.risk_center.domain.portfolio_exposure_types import EffectiveEndState
from apps.risk_center.domain.portfolio_risk_snapshot import OpenOrder, ProposedOrder
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
)
from tests.unit.risk_center.test_portfolio_baseline_risk import (
    _AS_OF,
)
from tests.unit.risk_center.test_portfolio_baseline_risk import _asset as _baseline_asset
from tests.unit.risk_center.test_portfolio_baseline_risk import (
    _native_limits,
    _parameters,
)
from tests.unit.risk_center.test_portfolio_baseline_risk import _policy as _baseline_policy
from tests.unit.risk_center.test_portfolio_baseline_risk import _projection as _baseline_projection
from tests.unit.risk_center.test_portfolio_baseline_risk import _snapshot as _baseline_snapshot
from tests.unit.risk_center.test_portfolio_capacity import _AS_OF as _CAPACITY_AS_OF
from tests.unit.risk_center.test_portfolio_capacity import _evaluate as _evaluate_capacity
from tests.unit.risk_center.test_portfolio_capacity import _observation as _capacity_observation
from tests.unit.risk_center.test_portfolio_capacity import _order as _capacity_order
from tests.unit.risk_center.test_portfolio_capacity import (
    _state_evidence as _capacity_state_evidence,
)
from tests.unit.risk_center.test_portfolio_capacity import _usage as _capacity_usage
from tests.unit.risk_center.test_portfolio_exposure import (
    BUSINESS_DATE,
)
from tests.unit.risk_center.test_portfolio_exposure import _coverage as _industry_coverage
from tests.unit.risk_center.test_portfolio_exposure import _equity as _industry_equity
from tests.unit.risk_center.test_portfolio_exposure import _membership as _industry_membership
from tests.unit.risk_center.test_portfolio_exposure import _policy as _industry_policy
from tests.unit.risk_center.test_portfolio_exposure import _projection as _industry_projection
from tests.unit.risk_center.test_portfolio_exposure import _source as _industry_source


def test_zero_total_limit_vetoes_positive_exposure_but_allows_zero_exposure() -> None:
    """An exact zero cap remains active; it is not interpreted as disabled policy."""

    policy = _baseline_policy(total="0", single="1", cash="0")
    snapshot = _baseline_snapshot()
    empty = assess_portfolio_baseline(
        policy=policy,
        snapshot=snapshot,
        projection=_baseline_projection(),
        proposals=(),
        as_of=_AS_OF,
    )
    positive = assess_portfolio_baseline(
        policy=policy,
        snapshot=snapshot,
        projection=_baseline_projection(_baseline_asset("AAA", Decimal("0.01"))),
        proposals=(),
        as_of=_AS_OF,
    )

    assert empty.outcome == "allowed"
    assert positive.outcome == "blocked"
    assert positive.projected_total_value == Decimal("0.01")
    assert "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT" in positive.reason_codes


def test_unknown_total_template_does_not_hide_a_known_single_position_veto() -> None:
    """A missing total template limit remains unknown while an independent single cap vetoes."""

    result = assess_portfolio_baseline(
        policy=_baseline_policy(total=None, single="0.5", cash="0.2"),
        snapshot=_baseline_snapshot(),
        projection=_baseline_projection(_baseline_asset("AAA", Decimal("501"))),
        proposals=(),
        as_of=_AS_OF,
    )

    assert result.outcome == "blocked"
    assert "PORTFOLIO_BASELINE_LIMIT_UNKNOWN" in result.reason_codes
    assert "PORTFOLIO_BASELINE_SINGLE_POSITION_LIMIT" in result.reason_codes
    assert "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT" not in result.reason_codes


def test_cash_shortfall_keeps_sell_proceeds_out_of_committed_cash() -> None:
    """Open and proposed sells never fund BUY reservations, including their fee budgets."""

    snapshot = _baseline_snapshot(
        cash=Decimal("100"),
        active_orders=(
            OpenOrder(
                "buy-hold",
                "AAA",
                "sec-a",
                "buy",
                Decimal("8"),
                Decimal("80"),
                Decimal("80"),
            ),
            OpenOrder(
                "sell-hold",
                "BBB",
                "sec-b",
                "sell",
                Decimal("1"),
                Decimal("400"),
                Decimal("0"),
            ),
        ),
    )
    proposals = (
        ProposedOrder("buy-new", "CCC", "sec-c", "buy", Decimal("1"), Decimal("20"), Decimal("5")),
        ProposedOrder(
            "sell-new", "DDD", "sec-d", "sell", Decimal("1"), Decimal("400"), Decimal("2")
        ),
    )
    result = assess_portfolio_baseline(
        policy=_baseline_policy(total="1", single="1", cash="0.1"),
        snapshot=snapshot,
        projection=_baseline_projection(),
        proposals=proposals,
        as_of=_AS_OF,
    )

    assert result.outcome == "blocked"
    assert result.cash_after_committed_demands == Decimal("-7")
    assert "PORTFOLIO_BASELINE_INSUFFICIENT_CASH" in result.reason_codes
    assert "PORTFOLIO_BASELINE_CASH_FLOOR" in result.reason_codes


def test_unknown_cash_and_unpriced_cash_hold_are_not_replaced_with_zero() -> None:
    """Unknown account cash or reservation cash stays unknown even with other measures present."""

    policy = _baseline_policy(total="1", single="1", cash="0")
    unknown_cash = assess_portfolio_baseline(
        policy=policy,
        snapshot=_baseline_snapshot(cash=None),
        projection=_baseline_projection(),
        proposals=(),
        as_of=_AS_OF,
    )
    missing_hold_cash = assess_portfolio_baseline(
        policy=policy,
        snapshot=_baseline_snapshot(
            cash=Decimal("100"),
            active_orders=(
                OpenOrder(
                    "reserved-buy",
                    "AAA",
                    "sec-a",
                    "buy",
                    Decimal("8"),
                    Decimal("80"),
                    None,
                ),
            ),
        ),
        projection=_baseline_projection(),
        proposals=(),
        as_of=_AS_OF,
    )

    assert unknown_cash.outcome == "unknown"
    assert unknown_cash.cash_after_committed_demands is None
    assert "PORTFOLIO_BASELINE_CASH_UNKNOWN" in unknown_cash.reason_codes
    assert missing_hold_cash.outcome == "unknown"
    assert missing_hold_cash.cash_after_committed_demands is None
    assert "PORTFOLIO_BASELINE_CASH_HOLD_UNKNOWN" in missing_hold_cash.reason_codes


def test_duplicate_proposal_identity_blocks_instead_of_double_counting_one_order() -> None:
    """The same proposal id cannot represent two simultaneous exposure additions."""

    proposals = (
        ProposedOrder("same-id", "AAA", "sec-a", "buy", Decimal("1"), Decimal("10"), Decimal("0")),
        ProposedOrder("same-id", "BBB", "sec-b", "buy", Decimal("1"), Decimal("10"), Decimal("0")),
    )
    result = assess_portfolio_baseline(
        policy=_baseline_policy(total="1", single="1", cash="0"),
        snapshot=_baseline_snapshot(),
        projection=_baseline_projection(),
        proposals=proposals,
        as_of=_AS_OF,
    )

    assert result.outcome == "blocked"
    assert "PORTFOLIO_BASELINE_PROPOSAL_ID_DUPLICATE" in result.reason_codes


@pytest.mark.parametrize(
    ("native_total", "expected_total", "projected_value"),
    [
        (Decimal("0.65"), Decimal("0.65"), Decimal("650.01")),
        (Decimal("0.75"), Decimal("0.70"), Decimal("700.01")),
    ],
)
def test_native_cap_and_global_floor_keep_the_tighter_total_limit(
    native_total: Decimal,
    expected_total: Decimal,
    projected_value: Decimal,
) -> None:
    """Native percentage caps may tighten a floor but never relax its effective bound."""

    resolved = resolve_portfolio_baseline_parameters(
        template=_parameters(total="0.9", single="0.9", cash="0"),
        overrides=_parameters(total="0.8", single="0.9", cash="0"),
        floor=_parameters(total="0.7", single="0.8", cash="0"),
        exceptions=(),
    )
    source_policy = _baseline_policy(
        total=str(resolved.max_total_weight),
        single=str(resolved.max_single_weight),
        cash=str(resolved.min_cash_weight),
    )
    native = _native_limits(single=Decimal("0.9"), total=native_total)
    effective_policy = intersect_native_account_limits(source_policy, native, _AS_OF)
    assert resolved.max_total_weight == Decimal("0.7")
    assert effective_policy is not None
    assert effective_policy.max_total_weight == expected_total
    assert effective_policy.max_single_weight == Decimal("0.8")

    result = assess_portfolio_baseline(
        policy=effective_policy,
        snapshot=_baseline_snapshot(),
        projection=_baseline_projection(_baseline_asset("AAA", projected_value)),
        proposals=(),
        as_of=_AS_OF,
    )
    assert result.outcome == "blocked"
    assert "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT" in result.reason_codes
    assert "PORTFOLIO_BASELINE_SINGLE_POSITION_LIMIT" not in result.reason_codes


def test_partial_execution_session_state_cannot_create_capacity() -> None:
    """A partly observed execution status cannot be treated as an open market session."""

    state = replace(
        _capacity_state_evidence(),
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.PARTIAL,
            precision_basis="execution_session_trading_state",
            expected_item_count=1,
            observed_item_count=0,
        ),
    )
    decision = _evaluate_capacity(
        observation=_capacity_observation(state_evidence=state),
    )

    assert decision.status == "unknown"
    assert "CAPACITY_TRADING_STATUS_COVERAGE_INCOMPLETE" in decision.reason_codes
    assert decision.window_capacity is None
    assert decision.allowed_new_capacity is None


def test_duplicate_capacity_order_identity_cannot_be_counted_as_two_distinct_uses() -> None:
    """The same order id in active and proposed sets makes gross usage indeterminate."""

    duplicate_active = _capacity_order(
        "same-order",
        side="buy",
        volume=CapacityValue(Decimal("10"), "share"),
    )
    duplicate_proposed = _capacity_order(
        "same-order",
        side="buy",
        volume=CapacityValue(Decimal("10"), "share"),
    )
    decision = _evaluate_capacity(
        observation=_capacity_observation(),
        usage=_capacity_usage(
            active_orders=(duplicate_active,),
            proposed_orders=(duplicate_proposed,),
        ),
    )

    assert decision.status == "unknown"
    assert "CAPACITY_DUPLICATE_ORDER_ID" in decision.reason_codes
    assert decision.remaining_capacity is None
    assert decision.allowed_new_capacity is None


def test_execution_status_from_another_session_cannot_qualify_current_capacity() -> None:
    """A fully clocked open status for yesterday does not prove today's trading state."""

    usage = _capacity_usage()
    other_session = usage.capacity_date - timedelta(days=1)
    state = _capacity_state_evidence(effective_on=other_session)
    decision = _evaluate_capacity(
        observation=_capacity_observation(
            state_date=other_session,
            state_evidence=state,
        ),
        usage=usage,
    )

    assert decision.status == "unknown"
    assert "CAPACITY_TRADING_STATUS_SESSION_DATE_MISMATCH" in decision.reason_codes
    assert decision.allowed_new_capacity is None


def test_capacity_snapshot_read_after_cutoff_cannot_support_available_remainder() -> None:
    """A future order-usage read cannot be mixed into an earlier decision cutoff."""

    usage = replace(
        _capacity_usage(),
        snapshot_read_at=_CAPACITY_AS_OF + timedelta(seconds=1),
    )
    decision = _evaluate_capacity(usage=usage)

    assert decision.status == "unknown"
    assert "CAPACITY_USAGE_AFTER_CUTOFF" in decision.reason_codes
    assert decision.remaining_capacity is None
    assert decision.allowed_new_capacity is None


def test_capacity_source_quantity_unit_must_match_policy_measure() -> None:
    """A currency amount cannot be interpreted as share volume by a volume policy."""

    observation = replace(
        _capacity_observation(),
        volume=CapacityValue(Decimal("10000"), "CNY"),
    )
    decision = _evaluate_capacity(observation=observation)

    assert decision.status == "unknown"
    assert "CAPACITY_SOURCE_UNIT_MISMATCH" in decision.reason_codes
    assert decision.window_capacity is None
    assert decision.allowed_new_capacity is None


def test_capacity_executed_quantity_unit_must_match_policy_measure() -> None:
    """A completed execution total with the wrong physical unit cannot reduce capacity."""

    usage = replace(
        _capacity_usage(used=CapacityValue(Decimal("10"), "share")),
        volume=CapacityValue(Decimal("10"), "CNY"),
    )
    decision = _evaluate_capacity(usage=usage)

    assert decision.status == "unknown"
    assert "CAPACITY_USED_UNIT_MISMATCH" in decision.reason_codes
    assert decision.remaining_capacity is None
    assert decision.allowed_new_capacity is None


def test_rolling_capacity_window_cannot_include_the_execution_session() -> None:
    """Historical capacity observations must end before the session being authorized."""

    observation = _capacity_observation()
    usage = _capacity_usage(capacity_date=observation.window_end)
    decision = _evaluate_capacity(observation=observation, usage=usage)

    assert decision.status == "unknown"
    assert "CAPACITY_LOOKBACK_NOT_BEFORE_EXECUTION_SESSION" in decision.reason_codes
    assert decision.allowed_new_capacity is None


def test_unknown_etf_coverage_does_not_promote_named_rows_to_known_exposure() -> None:
    """A constituent list without a coverage denominator leaves the whole ETF unknown."""

    report_date = date(2026, 6, 30)
    report = ETFConstituentReport(
        report_date=report_date,
        source_evidence=_industry_source(
            "unknown-etf-coverage",
            observed_on=BUSINESS_DATE,
            effective_on=report_date,
            coverage=PortfolioRiskCoverage(
                status=CoverageStatus.UNKNOWN,
                precision_basis="official_nav_weight",
            ),
        ),
        constituents=(
            ETFConstituent(
                asset_code="600001.SH",
                weight_fraction=Decimal("0.60"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=_industry_membership(
                    "IND-A",
                    source_id="unknown-coverage-member",
                ),
            ),
        ),
    )
    etf = PortfolioRiskAsset(
        asset_code="510050.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("100"),
        valuation_evidence=_industry_source("etf-valuation"),
        industry_membership=None,
        etf_report=report,
    )

    assessment = assess_portfolio_industry_exposure(
        policy=_industry_policy(
            minimum_industry_coverage=Decimal("0"),
            minimum_etf_coverage=Decimal("0"),
        ),
        projection=_industry_projection(etf),
    )

    fund = assessment.etf_bounds[0]
    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert "ETF_LOOKTHROUGH_COVERAGE_UNTRUSTED" in assessment.reason_codes
    assert fund.known_industry_market_value == Decimal("0")
    assert fund.unknown_market_value == Decimal("100")
    assert fund.unknown_security_market_value == Decimal("100")


def test_unknown_industry_membership_end_state_blocks_date_only_classification() -> None:
    """A missing end boundary cannot be inferred from an otherwise current membership."""

    membership = replace(
        _industry_membership("IND-A", source_id="unknown-membership-end"),
        effective_end_state=EffectiveEndState.UNKNOWN,
    )
    asset = _industry_equity("600001.SH", "200", "IND-A", membership=membership)
    assessment = assess_portfolio_industry_exposure(
        policy=_industry_policy(minimum_industry_coverage=Decimal("0")),
        projection=_industry_projection(asset),
    )

    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert "INDUSTRY_MEMBERSHIP_EFFECTIVE_END_UNKNOWN" in assessment.reason_codes
    assert assessment.unknown_industry_market_value == Decimal("200")


def test_bounded_industry_membership_includes_its_final_effective_date() -> None:
    """An explicit inclusive effective-until date qualifies on that business date."""

    membership = _industry_membership("IND-A", source_id="bounded-membership")
    evidence = replace(membership.source_evidence, effective_until=BUSINESS_DATE)
    bounded = replace(
        membership,
        effective_end_state=EffectiveEndState.BOUNDED,
        effective_until=BUSINESS_DATE,
        source_evidence=evidence,
    )
    assessment = assess_portfolio_industry_exposure(
        policy=_industry_policy(minimum_industry_coverage=Decimal("1")),
        projection=_industry_projection(
            _industry_equity("600001.SH", "200", "IND-A", membership=bounded)
        ),
    )

    assert assessment.outcome is ExposureOutcome.WITHIN_LIMIT
    assert assessment.industry_coverage_fraction == Decimal("1")
    assert assessment.unknown_industry_market_value == Decimal("0")


def test_membership_cannot_be_marked_open_when_source_record_has_an_end_date() -> None:
    """A dated source record cannot be relabelled as unbounded current membership."""

    bounded = _industry_membership("IND-A", source_id="bounded-source-record")
    ended_evidence = replace(
        bounded.source_evidence,
        effective_until=BUSINESS_DATE,
    )
    with pytest.raises(ValueError, match="membership end date differs"):
        replace(
            bounded,
            effective_end_state=EffectiveEndState.OPEN,
            effective_until=None,
            source_evidence=ended_evidence,
        )

    with pytest.raises(ValueError, match="bounded membership requires"):
        replace(
            bounded,
            effective_end_state=EffectiveEndState.BOUNDED,
            effective_until=None,
        )


def test_etf_constituent_weights_cannot_exceed_net_asset_value() -> None:
    """Reported constituent weights over 100% are rejected instead of normalized silently."""

    report_date = date(2026, 6, 30)
    evidence = _industry_source(
        "overweight-etf-report",
        observed_on=BUSINESS_DATE,
        effective_on=report_date,
        coverage=_industry_coverage(
            fraction=Decimal("1"),
            status=CoverageStatus.COMPLETE,
        ),
    )

    with pytest.raises(ValueError, match="cannot exceed the ETF net asset value"):
        ETFConstituentReport(
            report_date=report_date,
            source_evidence=evidence,
            constituents=(
                ETFConstituent(
                    asset_code="600001.SH",
                    weight_fraction=Decimal("0.70"),
                    kind=ETFConstituentKind.EQUITY,
                    industry_membership=None,
                ),
                ETFConstituent(
                    asset_code="600002.SH",
                    weight_fraction=Decimal("0.40"),
                    kind=ETFConstituentKind.EQUITY,
                    industry_membership=None,
                ),
            ),
        )


@pytest.mark.parametrize(
    ("status", "fraction", "expected", "observed", "message"),
    [
        (CoverageStatus.COMPLETE, Decimal("0.80"), 5, 4, "complete coverage"),
        (CoverageStatus.PARTIAL, Decimal("1"), 5, 5, "partial coverage"),
        (CoverageStatus.PARTIAL, Decimal("0.80"), 4, 5, "valid range"),
    ],
)
def test_source_coverage_claims_cannot_conflict_with_weight_or_item_counts(
    status: CoverageStatus,
    fraction: Decimal,
    expected: int,
    observed: int,
    message: str,
) -> None:
    """Coverage denominators must substantiate complete/partial status and exact counts."""

    with pytest.raises(ValueError, match=message):
        PortfolioRiskCoverage(
            status=status,
            precision_basis="official_nav_weight",
            reported_weight_fraction=fraction,
            expected_item_count=expected,
            observed_item_count=observed,
        )
