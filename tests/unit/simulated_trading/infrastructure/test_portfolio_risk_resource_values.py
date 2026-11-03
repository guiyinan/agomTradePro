"""Pure boundaries for native simulated account risk resource values."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    NativeAccountRiskLimits,
)
from apps.simulated_trading.infrastructure.portfolio_risk_resource_repository import (
    DjangoPortfolioRiskResourceRepository,
)


def test_native_float_field_percent_is_converted_to_an_exact_fraction() -> None:
    """Only the two configuration percentages use Decimal(str(value)) conversion."""

    assert DjangoPortfolioRiskResourceRepository._weight_from_percent(
        20.0,
        reason_code="native_single_weight_unknown",
    ) == (Decimal("0.2"), None)
    assert DjangoPortfolioRiskResourceRepository._weight_from_percent(
        95.0,
        reason_code="native_total_weight_unknown",
    ) == (Decimal("0.95"), None)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -1.0, 101.0])
def test_invalid_native_account_percent_stays_unknown_with_a_specific_reason(
    value: object,
) -> None:
    """Missing or invalid account fields never fall back to a built-in percentage."""

    assert DjangoPortfolioRiskResourceRepository._weight_from_percent(
        value,
        reason_code="native_single_weight_unknown",
    ) == (None, "native_single_weight_unknown")


def test_unavailable_scope_contains_no_account_values_or_identity_hints() -> None:
    """An inaccessible account uses one non-disclosing envelope shape."""

    result = DjangoPortfolioRiskResourceRepository._unavailable_scope()

    assert result.snapshot is None
    assert result.scope is None
    assert result.native_account_limits is None
    assert result.reason_codes == ()
    assert result.identity_issues == ()


def test_native_limits_require_exact_unknown_reasons() -> None:
    """Unknown values carry a field-specific reason and source basis."""

    limits = NativeAccountRiskLimits(
        max_single_weight=None,
        max_total_weight=Decimal("0.95"),
        reason_codes=("native_single_weight_unknown",),
        basis="simulated_account_percent_fields",
    )

    assert limits.max_single_weight is None
    assert limits.max_total_weight == Decimal("0.95")

    with pytest.raises(ValueError, match="exactly describe"):
        NativeAccountRiskLimits(
            max_single_weight=None,
            max_total_weight=Decimal("0.95"),
            reason_codes=(),
            basis="simulated_account_percent_fields",
        )
