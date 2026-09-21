"""Pure Domain tests for governed numeric tolerance policies."""

from dataclasses import replace

import pytest

from apps.data_center.domain.numeric_tolerance import (
    NumericToleranceField,
    NumericTolerancePolicy,
    compare_numeric_value,
)


def _field() -> NumericToleranceField:
    return NumericToleranceField(
        field_name="close",
        unit="CNY/share",
        absolute_tolerance="0.01",
        relative_tolerance="0.001",
    )


def _policy() -> NumericTolerancePolicy:
    return NumericTolerancePolicy(
        dataset_key="equity.price.bar",
        policy_version="owner-v1",
        rule="absolute_or_relative",
        fields=(_field(),),
    )


def test_policy_identity_binds_dataset_version_rule_field_unit_and_thresholds() -> None:
    policy = _policy()
    assert policy.identity == f"data02-tolerance-v1:owner-v1:{policy.content_hash}"
    assert len(policy.content_hash) == 64

    changed = (
        replace(policy, dataset_key="equity.quote.snapshot"),
        replace(policy, policy_version="owner-v2"),
        replace(policy, fields=(replace(_field(), field_name="open"),)),
        replace(policy, fields=(replace(_field(), unit="CNY"),)),
        replace(policy, fields=(replace(_field(), absolute_tolerance="0.02"),)),
        replace(policy, fields=(replace(_field(), relative_tolerance="0.002"),)),
    )
    assert all(item.content_hash != policy.content_hash for item in changed)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e-3", "", ".1", "+1"])
def test_thresholds_reject_noncanonical_or_nonfinite_decimals(value: str) -> None:
    with pytest.raises(ValueError, match="decimal string"):
        replace(_field(), absolute_tolerance=value)


def test_thresholds_are_nonnegative_and_policy_fields_are_unique() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        replace(_field(), absolute_tolerance="-0.01")
    with pytest.raises(ValueError, match="unique"):
        replace(_policy(), fields=(_field(), _field()))


def test_absolute_or_relative_boundary_is_inclusive() -> None:
    comparison = compare_numeric_value(
        natural_key="000001.SZ:2026-09-21:none",
        tolerance=_field(),
        unit="CNY/share",
        canonical_value="10",
        observed_value="10.01",
    )
    assert comparison.absolute_difference == "0.01"
    assert comparison.relative_difference == "0.001"
    assert comparison.breached is False


def test_relative_tolerance_can_accept_when_absolute_limit_is_exceeded() -> None:
    comparison = compare_numeric_value(
        natural_key="000001.SZ:2026-09-21:none",
        tolerance=_field(),
        unit="CNY/share",
        canonical_value="1000",
        observed_value="1000.5",
    )
    assert comparison.absolute_difference == "0.5"
    assert comparison.relative_difference == "0.0005"
    assert comparison.breached is False


def test_zero_canonical_value_has_no_fabricated_relative_difference() -> None:
    comparison = compare_numeric_value(
        natural_key="000001.SZ:2026-09-21:none",
        tolerance=_field(),
        unit="CNY/share",
        canonical_value="0",
        observed_value="0.02",
    )
    assert comparison.relative_difference is None
    assert comparison.breached is True


def test_large_exact_decimals_are_not_rounded_by_decimal_context() -> None:
    canonical = "1234567890123456789012345678901234567890.123456789"
    comparison = compare_numeric_value(
        natural_key="000001.SZ:2026-09-21:none",
        tolerance=replace(
            _field(),
            absolute_tolerance="0",
            relative_tolerance="0",
        ),
        unit="CNY/share",
        canonical_value=canonical,
        observed_value=canonical,
    )

    assert comparison.canonical_value == canonical
    assert comparison.observed_value == canonical
    assert comparison.absolute_difference == "0"
    assert comparison.relative_difference == "0"
    assert comparison.breached is False


def test_tiny_computed_relative_difference_uses_plain_decimal_not_exponent() -> None:
    comparison = compare_numeric_value(
        natural_key="000001.SZ:2026-09-21:none",
        tolerance=replace(
            _field(),
            absolute_tolerance="0",
            relative_tolerance="0.00000000000000000000000000000000000000000000000001",
        ),
        unit="CNY/share",
        canonical_value="100000000000000000000000000000000000000000000000000",
        observed_value="100000000000000000000000000000000000000000000000001",
    )

    assert comparison.absolute_difference == "1"
    assert comparison.relative_difference == (
        "0.00000000000000000000000000000000000000000000000001"
    )
    assert comparison.breached is False
