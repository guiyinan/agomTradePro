"""Focused direction-specific order admission contracts."""

from __future__ import annotations

import pytest

from apps.risk_center.domain.portfolio_risk_order_admission import (
    PortfolioRiskAdmissionCheck,
    assess_portfolio_risk_order_admission,
)


def test_sell_waives_only_known_existing_buy_position_and_cash_limits() -> None:
    checks = (
        PortfolioRiskAdmissionCheck("source_inputs", "allowed", ()),
        PortfolioRiskAdmissionCheck(
            "baseline_risk",
            "blocked",
            (
                "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",
                "PORTFOLIO_BASELINE_SINGLE_POSITION_LIMIT",
                "PORTFOLIO_BASELINE_INSUFFICIENT_CASH",
                "PORTFOLIO_BASELINE_CASH_FLOOR",
            ),
        ),
        PortfolioRiskAdmissionCheck("liquidity_capacity", "allowed", ()),
    )

    result = assess_portfolio_risk_order_admission(
        side="sell", checks=checks, must_not_use_for_decision=False
    )

    assert result.outcome == "allowed"
    assert result.reason_codes == ()
    assert result.waived_reason_codes == (
        "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",
        "PORTFOLIO_BASELINE_SINGLE_POSITION_LIMIT",
        "PORTFOLIO_BASELINE_INSUFFICIENT_CASH",
        "PORTFOLIO_BASELINE_CASH_FLOOR",
    )


def test_buy_and_mixed_orders_keep_all_existing_limits_strict() -> None:
    checks = (
        PortfolioRiskAdmissionCheck(
            "baseline_risk", "blocked", ("PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",)
        ),
    )

    buy = assess_portfolio_risk_order_admission(
        side="buy", checks=checks, must_not_use_for_decision=False
    )
    mixed = assess_portfolio_risk_order_admission(
        side="mixed", checks=checks, must_not_use_for_decision=False
    )

    assert buy.outcome == "blocked"
    assert mixed.outcome == "blocked"
    assert buy.reason_codes == mixed.reason_codes
    assert buy.waived_reason_codes == mixed.waived_reason_codes == ()


def test_sell_cannot_waive_baseline_limit_when_report_is_not_decision_grade() -> None:
    result = assess_portfolio_risk_order_admission(
        side="sell",
        checks=(
            PortfolioRiskAdmissionCheck(
                "baseline_risk",
                "blocked",
                ("PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",),
            ),
        ),
        must_not_use_for_decision=True,
    )

    assert result.outcome == "unknown"
    assert "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT" in result.reason_codes
    assert result.waived_reason_codes == ()


@pytest.mark.parametrize(
    ("check", "must_not_use", "blocking_reason"),
    (
        (
            PortfolioRiskAdmissionCheck(
                "source_inputs", "unknown", ("RISK_SOURCE_EXPIRED_AT_CUTOFF",)
            ),
            True,
            "RISK_SOURCE_EXPIRED_AT_CUTOFF",
        ),
        (
            PortfolioRiskAdmissionCheck(
                "liquidity_capacity", "blocked", ("CAPACITY_REMAINDER_EXHAUSTED",)
            ),
            False,
            "CAPACITY_REMAINDER_EXHAUSTED",
        ),
        (
            PortfolioRiskAdmissionCheck(
                "liquidity_capacity", "blocked", ("CAPACITY_TRADING_SUSPENDED",)
            ),
            False,
            "CAPACITY_TRADING_SUSPENDED",
        ),
        (
            PortfolioRiskAdmissionCheck(
                "industry_and_security_exposure",
                "blocked",
                ("INDUSTRY_RISK_LIMIT_BREACHED",),
            ),
            False,
            "INDUSTRY_RISK_LIMIT_BREACHED",
        ),
        (
            PortfolioRiskAdmissionCheck(
                "baseline_risk",
                "blocked",
                (
                    "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",
                    "PORTFOLIO_BASELINE_HARD_EXCLUSION",
                ),
            ),
            False,
            "PORTFOLIO_BASELINE_HARD_EXCLUSION",
        ),
        (
            PortfolioRiskAdmissionCheck(
                "baseline_risk",
                "blocked",
                (
                    "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",
                    "PORTFOLIO_BASELINE_UNSUPPORTED_LIMIT",
                ),
            ),
            False,
            "PORTFOLIO_BASELINE_UNSUPPORTED_LIMIT",
        ),
        (
            PortfolioRiskAdmissionCheck(
                "resource_identity", "blocked", ("PORTFOLIO_LEDGER_IDENTITY_CONFLICT",)
            ),
            False,
            "PORTFOLIO_LEDGER_IDENTITY_CONFLICT",
        ),
    ),
)
def test_sell_waives_only_legacy_baseline_codes(
    check: PortfolioRiskAdmissionCheck, must_not_use: bool, blocking_reason: str
) -> None:
    result = assess_portfolio_risk_order_admission(
        side="sell",
        checks=(check,),
        must_not_use_for_decision=must_not_use,
    )

    assert result.outcome in {"blocked", "unknown"}
    assert blocking_reason in result.reason_codes
    if check.dimension == "baseline_risk" and not must_not_use:
        assert "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT" not in result.reason_codes
        assert "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT" in result.waived_reason_codes


def test_sell_waiver_cannot_override_partial_or_nonbaseline_checks() -> None:
    """Legacy BUY-limit waivers require a baseline check and never admit partial inputs."""

    baseline_breach = PortfolioRiskAdmissionCheck(
        "baseline_risk",
        "blocked",
        ("PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",),
    )
    partial_source = PortfolioRiskAdmissionCheck(
        "source_inputs",
        "partial",
        ("PORTFOLIO_SOURCE_COVERAGE_PARTIAL",),
    )
    partial_result = assess_portfolio_risk_order_admission(
        side="sell",
        checks=(baseline_breach, partial_source),
        must_not_use_for_decision=False,
    )

    assert partial_result.outcome == "unknown"
    assert partial_result.reason_codes == ("PORTFOLIO_SOURCE_COVERAGE_PARTIAL",)
    assert partial_result.waived_reason_codes == ("PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",)

    wrong_dimension = PortfolioRiskAdmissionCheck(
        "liquidity_capacity",
        "blocked",
        ("PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",),
    )
    wrong_dimension_result = assess_portfolio_risk_order_admission(
        side="sell",
        checks=(wrong_dimension,),
        must_not_use_for_decision=False,
    )

    assert wrong_dimension_result.outcome == "blocked"
    assert wrong_dimension_result.reason_codes == ("PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",)
    assert wrong_dimension_result.waived_reason_codes == ()


def test_sell_with_no_qualified_checks_is_unknown() -> None:
    """Missing risk checks do not turn a SELL limit waiver into a qualified decision."""

    result = assess_portfolio_risk_order_admission(
        side="sell",
        checks=(),
        must_not_use_for_decision=False,
    )

    assert result.outcome == "unknown"
    assert result.reason_codes == ("PORTFOLIO_ORDER_ADMISSION_CHECKS_MISSING",)
    assert result.waived_reason_codes == ()


def test_inconsistent_check_statuses_fail_closed_with_stable_reasons() -> None:
    """Allowed checks carrying blockers and unexplained blocks cannot authorize SELL."""

    contradictory = assess_portfolio_risk_order_admission(
        side="sell",
        checks=(
            PortfolioRiskAdmissionCheck(
                "source_inputs",
                "allowed",
                ("RISK_SOURCE_EXPIRED_AT_CUTOFF",),
            ),
        ),
        must_not_use_for_decision=False,
    )
    unexplained = assess_portfolio_risk_order_admission(
        side="sell",
        checks=(PortfolioRiskAdmissionCheck("baseline_risk", "blocked", ()),),
        must_not_use_for_decision=False,
    )

    assert contradictory.outcome == "blocked"
    assert contradictory.reason_codes == ("PORTFOLIO_ORDER_ADMISSION_ALLOWED_CHECK_HAS_REASONS",)
    assert unexplained.outcome == "blocked"
    assert unexplained.reason_codes == ("PORTFOLIO_ORDER_ADMISSION_CHECK_BLOCKED",)
