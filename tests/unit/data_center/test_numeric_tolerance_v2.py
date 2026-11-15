"""D1 per-metric comparisons retain real units and immutable v1 semantics."""

from dataclasses import replace

import pytest

from apps.data_center.domain import numeric_tolerance as numeric


def field(name="revenue", unit="元"):
    return numeric.NumericToleranceFieldV2(name, unit, "0", "0")


def policy():
    return numeric.NumericTolerancePolicyV2(
        dataset_key="equity.financial.fact",
        policy_version="test.v2",
        rule="absolute_or_relative",
        fields=(field(), field("roe", "%")),
        selector="financial_metric_code_v1",
    )


def test_each_financial_member_selects_only_its_actual_metric_and_unit():
    result = policy()
    assert result.fields_for_member(
        "000001.SZ:2026-06-30:semi_annual:revenue:akshare", source="akshare"
    ) == (field(),)
    assert result.fields_for_member(
        "000001.SZ:2026-06-30:semi_annual:roe:akshare", source="akshare"
    ) == (
        field("roe", "%"),
    )


@pytest.mark.parametrize(
    "key,source",
    [
        ("000001.SZ:2026-06-30:semi_annual:missing:akshare", "akshare"),
        ("000001.SZ:2026-06-30:semi_annual:roe:akshare:extra", "akshare"),
        ("000001.SZ:2026-06-30:semi_annual:roe:akshare", "tushare"),
        ("000001.SZ:2026-02-30:semi_annual:roe:akshare", "akshare"),
        ("000001.SZ:2026-06-30:unknown_period:roe:akshare", "akshare"),
        ("000001.sz:2026-06-30:semi_annual:roe:akshare", "akshare"),
    ],
)
def test_financial_selector_rejects_unknown_or_changed_member_identity(key, source):
    with pytest.raises(ValueError):
        policy().fields_for_member(key, source=source)


@pytest.mark.parametrize("unit", ["元", "%", "CNY", "shares", "倍"])
def test_v2_units_are_retained_without_aliasing(unit):
    value = field(unit=unit)
    assert value.unit == unit and value.to_dict()["unit"] == unit
    comparison = numeric.compare_numeric_value(
        natural_key="row-1",
        tolerance=value,
        unit=unit,
        canonical_value="12.0000",
        observed_value="12",
    )
    assert not comparison.breached and comparison.unit == unit


@pytest.mark.parametrize(
    "unit",
    [
        "",
        " 元",
        "元 ",
        "元\x00",
        "元\u200b",
        "e\u0301",
        "unknown",
        "native",
        "canonical-unit",
        "catalog",
        "Catalog",
    ],
)
def test_invalid_units_fail_instead_of_silent_cleanup(unit):
    with pytest.raises(ValueError):
        field(unit=unit)


def test_v2_cannot_hide_unit_drift_or_a_small_rounding_difference():
    with pytest.raises(ValueError, match="unit"):
        numeric.compare_numeric_value(
            natural_key="row-1",
            tolerance=field(),
            unit="万元",
            canonical_value="1",
            observed_value="1",
        )
    assert numeric.compare_numeric_value(
        natural_key="row-1",
        tolerance=field(),
        unit="元",
        canonical_value="1",
        observed_value="1.0001",
    ).breached


def test_selector_and_every_unit_are_bound_to_v2_identity():
    original = policy()
    assert original.identity.startswith("data02-tolerance-v2:")
    assert (
        replace(original, fields=(field(unit="万元"), field("roe", "%"))).content_hash
        != original.content_hash
    )
    with pytest.raises(ValueError):
        replace(original, selector="all_fields_per_member")


def test_v1_hash_and_ascii_unit_contract_are_unchanged():
    legacy = numeric.NumericTolerancePolicy(
        "equity.financial.fact",
        "legacy-test",
        "absolute_or_relative",
        (numeric.NumericToleranceField("value", "canonical-unit", "0", "0"),),
    )
    assert (
        legacy.identity
        == "data02-tolerance-v1:legacy-test:878f048dd6911da5aa219a85f92fdf141e25c8c373d989f18a0448a3f5e0c717"
    )
    with pytest.raises(ValueError):
        numeric.NumericToleranceField("value", "元", "0", "0")


def test_nonfinancial_v2_requires_each_configured_field_for_each_member():
    cls = numeric.NumericTolerancePolicyV2
    configured = cls(
        "equity.price.bar",
        "v2",
        "absolute_or_relative",
        (field("close", "CNY"), field("volume", "shares")),
        "all_fields_per_member",
    )
    assert (
        configured.fields_for_member("000001.SZ:2026-06-30:akshare", source="akshare")
        == configured.fields
    )
    with pytest.raises(ValueError):
        replace(configured, selector="financial_metric_code_v1")


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("rule", "approximate"),
        ("fields", ()),
        ("fields", []),
        ("fields", (field("roe", "%"), field("roe", "元"))),
        ("fields", (field("roe:other", "%"),)),
        ("policy_version", ""),
    ],
)
def test_v2_policy_rejects_ambiguous_or_unversioned_matrix(attribute, value):
    with pytest.raises(ValueError):
        replace(policy(), **{attribute: value})


@pytest.mark.parametrize(
    "name,value",
    [
        ("absolute_tolerance", "-1"),
        ("relative_tolerance", "-1"),
        ("absolute_tolerance", "NaN"),
        ("relative_tolerance", "1e-5"),
    ],
)
def test_v2_never_admits_negative_or_noncanonical_tolerances(name, value):
    with pytest.raises(ValueError):
        replace(field(), **{name: value})


def test_financial_matrix_requires_all_metrics_for_every_report_group():
    revenue = "000001.SZ:2026-06-30:semi_annual:revenue:akshare"
    roe = "000001.SZ:2026-06-30:semi_annual:roe:akshare"
    configured = policy()
    configured.validate_member_coverage(((revenue, "akshare"), (roe, "akshare")))
    with pytest.raises(ValueError, match="omits governed metrics"):
        configured.validate_member_coverage(((revenue, "akshare"),))
    with pytest.raises(ValueError, match="duplicated"):
        configured.validate_member_coverage(((revenue, "akshare"), (revenue, "akshare")))
    with pytest.raises(ValueError, match="empty"):
        configured.validate_member_coverage(())
