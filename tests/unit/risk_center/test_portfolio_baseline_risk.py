"""Exact boundary tests for the existing four-dimension baseline policy."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.risk_center.domain.portfolio_baseline_risk import (
    BaselineRiskException,
    BaselineRiskParameters,
    PortfolioBaselinePolicy,
    PortfolioBaselineRiskError,
    assess_portfolio_baseline,
    intersect_native_account_limits,
    resolve_portfolio_baseline_parameters,
)
from apps.risk_center.domain.portfolio_exposure_types import (
    PortfolioAssetKind,
    PortfolioExposureProjection,
    PortfolioRiskAsset,
)
from apps.risk_center.domain.portfolio_risk_native_limits import (
    PortfolioRiskNativeAccountLimits,
)
from apps.risk_center.domain.portfolio_risk_serialization import (
    portfolio_risk_content_hash,
)
from apps.risk_center.domain.portfolio_risk_snapshot import (
    AccountSnapshot,
    OpenOrder,
    ProposedOrder,
)

_AS_OF = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
_DATE = date(2026, 11, 3)


def _parameters(
    *,
    total: str | None = "1",
    single: str | None = "1",
    cash: str | None = "0",
    exclusions: tuple[str, ...] = (),
) -> BaselineRiskParameters:
    return BaselineRiskParameters(
        max_total_weight=None if total is None else Decimal(total),
        max_single_weight=None if single is None else Decimal(single),
        min_cash_weight=None if cash is None else Decimal(cash),
        hard_exclusions=exclusions,
    )


def _policy(
    *,
    account_id: int = 7,
    total: str | None = "1",
    single: str | None = "1",
    cash: str | None = "0",
    exclusions: tuple[str, ...] = (),
    effective_until: datetime | None = None,
) -> PortfolioBaselinePolicy:
    return PortfolioBaselinePolicy(
        account_id=account_id,
        account_policy_id=70,
        content_sha256="a" * 64,
        known_at=_AS_OF - timedelta(minutes=1),
        effective_until=effective_until,
        max_total_weight=None if total is None else Decimal(total),
        max_single_weight=None if single is None else Decimal(single),
        min_cash_weight=None if cash is None else Decimal(cash),
        hard_exclusions=exclusions,
    )


def _snapshot(
    *,
    cash: Decimal | None = Decimal("1000"),
    money_unit: str | None = "CNY",
    active_orders: tuple[OpenOrder, ...] = (),
    active_orders_complete: bool = True,
) -> AccountSnapshot:
    return AccountSnapshot(
        account_id=7,
        owner_user_id=11,
        snapshot_id="snapshot-7",
        read_at=_AS_OF - timedelta(seconds=1),
        cash=cash,
        money_unit=money_unit,
        holdings=(),
        active_orders=active_orders,
        executed_usage=(),
        active_orders_complete=active_orders_complete,
        execution_session=_DATE,
        executed_usage_complete=True,
    )


def _asset(asset_code: str, value: Decimal | None) -> PortfolioRiskAsset:
    return PortfolioRiskAsset(
        asset_code=asset_code,
        kind=PortfolioAssetKind.EQUITY,
        projected_market_value=value,
        valuation_evidence=None,
        industry_membership=None,
        etf_report=None,
    )


def _projection(
    *assets: PortfolioRiskAsset,
    nav: Decimal = Decimal("1000"),
    snapshot_id: str = "snapshot-7",
) -> PortfolioExposureProjection:
    return PortfolioExposureProjection(
        portfolio_snapshot_id=snapshot_id,
        as_of=_AS_OF,
        business_date=_DATE,
        portfolio_market_value=nav,
        assets=tuple(assets),
    )


def _native_limits(
    *,
    single: Decimal | None,
    total: Decimal | None,
) -> PortfolioRiskNativeAccountLimits:
    missing_reasons = tuple(
        reason
        for value, reason in (
            (single, "native_single_weight_unknown"),
            (total, "native_total_weight_unknown"),
        )
        if value is None
    )
    return PortfolioRiskNativeAccountLimits(
        max_single_weight=single,
        max_total_weight=total,
        reason_codes=missing_reasons,
        basis="simulated_account_percent_fields",
    )


def test_native_intersection_keeps_unknown_fields_and_zero_as_a_strict_limit() -> None:
    source_policy = _policy(total="0.8", single="0.6", cash="0.1")
    native = _native_limits(single=Decimal("0"), total=None)
    read_at = _AS_OF + timedelta(seconds=1)

    effective = intersect_native_account_limits(source_policy, native, read_at)

    assert effective is not None
    assert effective.max_single_weight == Decimal("0")
    assert effective.max_total_weight is None
    assert effective.min_cash_weight == Decimal("0.1")
    assert effective.known_at == read_at
    assert effective.content_sha256 == portfolio_risk_content_hash(
        {
            "baseline_source_sha256": source_policy.content_sha256,
            "native_account_limits": native,
        }
    )
    assert source_policy.max_single_weight == Decimal("0.6")
    assert source_policy.max_total_weight == Decimal("0.8")
    assert source_policy.known_at == _AS_OF - timedelta(minutes=1)
    assert source_policy.content_sha256 == "a" * 64


def test_native_intersection_uses_minimum_and_native_only_changes_composite_digest() -> None:
    source_policy = _policy(total="0.7", single="0.5")
    read_at = _AS_OF + timedelta(seconds=1)
    native_first = _native_limits(single=Decimal("0.8"), total=Decimal("0.6"))
    native_tighter_total = _native_limits(single=Decimal("0.8"), total=Decimal("0.55"))

    first = intersect_native_account_limits(source_policy, native_first, read_at)
    tighter = intersect_native_account_limits(source_policy, native_tighter_total, read_at)

    assert first is not None and tighter is not None
    assert first.max_single_weight == Decimal("0.5")
    assert first.max_total_weight == Decimal("0.6")
    assert tighter.max_total_weight == Decimal("0.55")
    assert first.content_sha256 != tighter.content_sha256
    assert first.known_at == read_at
    assert tighter.known_at == read_at


@pytest.mark.parametrize(
    ("policy", "native", "read_at"),
    (
        (None, _native_limits(single=Decimal("0.5"), total=Decimal("0.6")), _AS_OF),
        (_policy(), None, _AS_OF),
        (
            _policy(),
            _native_limits(single=Decimal("0.5"), total=Decimal("0.6")),
            datetime(2026, 11, 3, 8, 0),
        ),
    ),
)
def test_native_intersection_returns_unknown_for_missing_inputs_or_naive_clock(
    policy: PortfolioBaselinePolicy | None,
    native: PortfolioRiskNativeAccountLimits | None,
    read_at: datetime,
) -> None:
    assert intersect_native_account_limits(policy, native, read_at) is None


def test_resolution_keeps_zero_override_and_applies_exact_floor_exceptions() -> None:
    """Legacy zero, stricter floors and scoped exception semantics stay intact."""

    result = resolve_portfolio_baseline_parameters(
        template=_parameters(total="0.8", single="0.3", cash="0.1", exclusions=("AAA", "BBB")),
        overrides=_parameters(total="0", single="0.5", cash="0.1", exclusions=()),
        floor=_parameters(total="0.6", single="0.4", cash="0.2", exclusions=("FLOOR",)),
        exceptions=(
            BaselineRiskException("max_single_weight", Decimal("0.45"), None),
            BaselineRiskException("min_cash_weight", Decimal("0.15"), None),
            BaselineRiskException("hard_exclusions", None, ("ONLY",)),
        ),
    )

    assert result == _parameters(
        total="0",
        single="0.45",
        cash="0.15",
        exclusions=("ONLY",),
    )


def test_empty_exclusion_override_falls_back_to_template_and_unions_floor() -> None:
    result = resolve_portfolio_baseline_parameters(
        template=_parameters(exclusions=("TEMPLATE",)),
        overrides=_parameters(exclusions=()),
        floor=_parameters(exclusions=("FLOOR",)),
        exceptions=(),
    )

    assert result.hard_exclusions == ("FLOOR", "TEMPLATE")


def test_multiple_active_exceptions_for_one_field_are_ambiguous() -> None:
    with pytest.raises(PortfolioBaselineRiskError) as error:
        resolve_portfolio_baseline_parameters(
            template=_parameters(),
            overrides=_parameters(),
            floor=_parameters(total="0.5"),
            exceptions=(
                BaselineRiskException("max_total_weight", Decimal("0.7"), None),
                BaselineRiskException("max_total_weight", Decimal("0.8"), None),
            ),
        )

    assert error.value.reason_code == "PORTFOLIO_BASELINE_EXCEPTION_AMBIGUOUS"


def test_exact_limit_boundaries_are_allowed_and_one_fraction_over_blocks() -> None:
    snapshot = _snapshot(cash=Decimal("200"))
    at_boundary = assess_portfolio_baseline(
        policy=_policy(total="0.8", single="0.5", cash="0.2"),
        snapshot=snapshot,
        projection=_projection(_asset("AAA", Decimal("500")), _asset("BBB", Decimal("300"))),
        proposals=(),
        as_of=_AS_OF,
    )
    over_single = assess_portfolio_baseline(
        policy=_policy(total="0.8", single="0.5", cash="0.2"),
        snapshot=snapshot,
        projection=_projection(
            _asset("AAA", Decimal("500.0001")), _asset("BBB", Decimal("299.9999"))
        ),
        proposals=(),
        as_of=_AS_OF,
    )

    assert at_boundary.outcome == "allowed"
    assert at_boundary.projected_total_value == Decimal("800")
    assert at_boundary.cash_after_committed_demands == Decimal("200")
    assert over_single.outcome == "blocked"
    assert "PORTFOLIO_BASELINE_SINGLE_POSITION_LIMIT" in over_single.reason_codes


def test_cash_subtracts_all_remaining_holds_and_proposal_buys_and_fees_only() -> None:
    """Open SELL proceeds do not offset either cash demand or active holds."""

    snapshot = _snapshot(
        active_orders=(
            OpenOrder(
                "buy-hold", "AAA", "sec-a", "buy", Decimal("2"), Decimal("100"), Decimal("100")
            ),
            OpenOrder(
                "sell-hold", "BBB", "sec-b", "sell", Decimal("1"), Decimal("80"), Decimal("10")
            ),
        )
    )
    proposals = (
        ProposedOrder("buy-new", "CCC", "sec-c", "buy", Decimal("3"), Decimal("50"), Decimal("5")),
        ProposedOrder(
            "sell-new", "DDD", "sec-d", "sell", Decimal("4"), Decimal("100"), Decimal("2")
        ),
    )
    result = assess_portfolio_baseline(
        policy=_policy(),
        snapshot=snapshot,
        projection=_projection(_asset("AAA", Decimal("700"))),
        proposals=proposals,
        as_of=_AS_OF,
    )

    assert result.outcome == "allowed"
    assert result.cash_after_committed_demands == Decimal("733")
    assert result.projected_total_value == Decimal("700")


def test_unfilled_sell_does_not_release_gross_exposure() -> None:
    result = assess_portfolio_baseline(
        policy=_policy(total="0.9"),
        snapshot=_snapshot(),
        projection=_projection(_asset("AAA", Decimal("1000"))),
        proposals=(
            ProposedOrder(
                "sell", "AAA", "sec-a", "sell", Decimal("5"), Decimal("100"), Decimal("0")
            ),
        ),
        as_of=_AS_OF,
    )

    assert result.outcome == "blocked"
    assert result.projected_total_value == Decimal("1000")
    assert "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT" in result.reason_codes


def test_hard_exclusion_applies_to_sell_proposals_too() -> None:
    result = assess_portfolio_baseline(
        policy=_policy(exclusions=("AAA",)),
        snapshot=_snapshot(),
        projection=_projection(_asset("AAA", Decimal("100"))),
        proposals=(
            ProposedOrder(
                "sell", "aaa", "sec-a", "sell", Decimal("1"), Decimal("10"), Decimal("0")
            ),
        ),
        as_of=_AS_OF,
    )

    assert result.outcome == "blocked"
    assert "PORTFOLIO_BASELINE_HARD_EXCLUSION" in result.reason_codes


def test_unknown_fee_or_incomplete_holds_never_become_zero_and_cash_is_unknown() -> None:
    unknown_fee = assess_portfolio_baseline(
        policy=_policy(),
        snapshot=_snapshot(),
        projection=_projection(_asset("AAA", Decimal("100"))),
        proposals=(ProposedOrder("buy", "AAA", "sec-a", "buy", Decimal("1"), Decimal("10"), None),),
        as_of=_AS_OF,
    )
    unknown_holds = assess_portfolio_baseline(
        policy=_policy(),
        snapshot=_snapshot(active_orders_complete=False),
        projection=_projection(_asset("AAA", Decimal("100"))),
        proposals=(),
        as_of=_AS_OF,
    )

    assert unknown_fee.outcome == "unknown"
    assert unknown_fee.cash_after_committed_demands is None
    assert "PORTFOLIO_BASELINE_FEE_BUDGET_UNKNOWN" in unknown_fee.reason_codes
    assert unknown_holds.outcome == "unknown"
    assert unknown_holds.cash_after_committed_demands is None
    assert "PORTFOLIO_BASELINE_CASH_HOLDS_INCOMPLETE" in unknown_holds.reason_codes


def test_exposure_unknown_does_not_erase_independently_known_cash() -> None:
    result = assess_portfolio_baseline(
        policy=_policy(),
        snapshot=_snapshot(cash=Decimal("150")),
        projection=_projection(_asset("AAA", None)),
        proposals=(),
        as_of=_AS_OF,
    )

    assert result.outcome == "unknown"
    assert result.cash_after_committed_demands == Decimal("150")
    assert result.projected_total_value is None


@pytest.mark.parametrize(
    ("snapshot", "projection", "policy", "as_of", "reason"),
    (
        (
            _snapshot(),
            _projection(_asset("AAA", Decimal("100"))),
            None,
            _AS_OF,
            "PORTFOLIO_BASELINE_POLICY_UNAVAILABLE",
        ),
        (
            _snapshot(),
            _projection(_asset("AAA", Decimal("100")), snapshot_id="other"),
            _policy(),
            _AS_OF,
            "PORTFOLIO_BASELINE_SNAPSHOT_OR_CUTOFF_MISMATCH",
        ),
        (
            _snapshot(),
            _projection(_asset("AAA", Decimal("100"))),
            _policy(account_id=8),
            _AS_OF,
            "PORTFOLIO_BASELINE_POLICY_SCOPE_OR_CLOCK_INVALID",
        ),
        (
            _snapshot(),
            _projection(_asset("AAA", Decimal("100"))),
            _policy(effective_until=_AS_OF),
            _AS_OF,
            "PORTFOLIO_BASELINE_POLICY_EXPIRED",
        ),
    ),
)
def test_unavailable_stale_or_mismatched_bindings_return_stable_unknown(
    snapshot: AccountSnapshot,
    projection: PortfolioExposureProjection,
    policy: PortfolioBaselinePolicy | None,
    as_of: datetime,
    reason: str,
) -> None:
    result = assess_portfolio_baseline(
        policy=policy,
        snapshot=snapshot,
        projection=projection,
        proposals=(),
        as_of=as_of,
    )

    assert result.outcome == "unknown"
    assert result.reason_codes == (reason,)


def test_unknown_money_unit_blocks_cash_comparison_instead_of_assuming_a_unit() -> None:
    result = assess_portfolio_baseline(
        policy=_policy(cash="0.1"),
        snapshot=_snapshot(cash=Decimal("5"), money_unit=None),
        projection=_projection(_asset("AAA", Decimal("100"))),
        proposals=(),
        as_of=_AS_OF,
    )

    assert result.outcome == "unknown"
    assert result.cash_after_committed_demands is None
    assert "PORTFOLIO_BASELINE_MONEY_UNIT_UNKNOWN" in result.reason_codes
