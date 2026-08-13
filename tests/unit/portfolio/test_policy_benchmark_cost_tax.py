"""Pure Domain tests for the policy benchmark cost/tax methodology."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.domain.policy_benchmark_cost_tax import (
    POLICY_BENCHMARK_COST_TAX_OWNER,
    POLICY_BENCHMARK_COST_TAX_PERMISSION,
    POLICY_BENCHMARK_COST_TAX_SCHEMA,
    POLICY_BENCHMARK_COST_TAX_TYPE,
    PolicyBenchmarkCostTaxRule,
    PolicyBenchmarkCostTaxSourceRef,
    PortfolioPolicyBenchmarkCostTax,
)

RECORDED_AT = datetime(2026, 8, 13, 8, tzinfo=UTC)
VALID_UNTIL = RECORDED_AT + timedelta(days=30)


def _source(
    ordinal: int,
    charge_kind: str,
    charge_code: str,
    *,
    asset_scope_code: str = "CN-EQUITY",
    jurisdiction_code: str = "CN",
    recorded_at: datetime = RECORDED_AT - timedelta(hours=1),
    valid_until: datetime = VALID_UNTIL,
) -> PolicyBenchmarkCostTaxSourceRef:
    artifact_type = {
        "fee": "benchmark_fee_definition",
        "tax": "benchmark_tax_definition",
    }[charge_kind]
    return PolicyBenchmarkCostTaxSourceRef(
        owner="portfolio-cost-authority",
        artifact_type=artifact_type,
        artifact_id=f"charge-{ordinal}",
        artifact_version="v1",
        content_hash=f"{ordinal + 1:064x}",
        ordinal=ordinal,
        charge_kind=charge_kind,
        charge_code=charge_code,
        asset_scope_code=asset_scope_code,
        jurisdiction_code=jurisdiction_code,
        recorded_at=recorded_at,
        valid_until=valid_until,
    )


def _fee_rule(**overrides: object) -> PolicyBenchmarkCostTaxRule:
    values: dict[str, object] = {
        "ordinal": 0,
        "source_ordinal": 0,
        "charge_kind": "fee",
        "charge_code": "broker-commission",
        "asset_scope_code": "CN-EQUITY",
        "jurisdiction_code": "CN",
        "charge_event": "trade",
        "trade_side": "both",
        "calculation_basis": "gross_trade_notional",
        "recognition_timing": "trade_execution",
        "calculation_mode": "rate",
        "rate": Decimal("0.00030000"),
        "fixed_amount": None,
        "minimum_amount": None,
        "maximum_amount": None,
        "charge_currency": "CNY",
        "rate_precision_places": 8,
        "amount_precision_places": 2,
        "rounding_increment": Decimal("0.01"),
        "rounding_mode": "half_up",
    }
    values.update(overrides)
    return PolicyBenchmarkCostTaxRule(**values)  # type: ignore[arg-type]


def _tax_rule(**overrides: object) -> PolicyBenchmarkCostTaxRule:
    values: dict[str, object] = {
        "ordinal": 1,
        "source_ordinal": 1,
        "charge_kind": "tax",
        "charge_code": "cash-dividend-withholding",
        "asset_scope_code": "CN-EQUITY",
        "jurisdiction_code": "CN",
        "charge_event": "cash_dividend",
        "trade_side": "not_applicable",
        "calculation_basis": "gross_cash_dividend_entitlement",
        "recognition_timing": "entitlement_recognition",
        "calculation_mode": "rate",
        "rate": Decimal("0.1000"),
        "fixed_amount": None,
        "minimum_amount": None,
        "maximum_amount": None,
        "charge_currency": "CNY",
        "rate_precision_places": 4,
        "amount_precision_places": 2,
        "rounding_increment": Decimal("0.0100"),
        "rounding_mode": "half_up",
    }
    values.update(overrides)
    return PolicyBenchmarkCostTaxRule(**values)  # type: ignore[arg-type]


def _methodology(**overrides: object) -> PortfolioPolicyBenchmarkCostTax:
    values: dict[str, object] = {
        "methodology_id": "policy-benchmark-cost-tax",
        "methodology_version": "v1",
        "source_priority": (
            _source(0, "fee", "broker-commission"),
            _source(1, "tax", "cash-dividend-withholding"),
        ),
        "charge_rules": (_fee_rule(), _tax_rule()),
        "recorded_at": RECORDED_AT,
        "valid_until": VALID_UNTIL,
    }
    values.update(overrides)
    return PortfolioPolicyBenchmarkCostTax(**values)  # type: ignore[arg-type]


def test_complete_definition_is_canonical_and_inactive() -> None:
    methodology = _methodology()
    payload = methodology.to_payload()

    assert methodology.owner == POLICY_BENCHMARK_COST_TAX_OWNER
    assert methodology.artifact_type == POLICY_BENCHMARK_COST_TAX_TYPE
    assert methodology.schema == POLICY_BENCHMARK_COST_TAX_SCHEMA
    assert methodology.permission == POLICY_BENCHMARK_COST_TAX_PERMISSION
    assert payload["charge_rules"][0]["rate"] == "0.0003"  # type: ignore[index]
    assert payload["charge_rules"][1]["rate"] == "0.1"  # type: ignore[index]
    assert payload["charge_rules"][1]["rounding_increment"] == "0.01"  # type: ignore[index]
    assert payload["business_date_policy"] == "benchmark_trading_calendar_date"
    assert payload["activation_available"] is False
    assert payload["automatic_fallback_allowed"] is False
    assert payload["must_not_execute"] is True
    assert "active" not in payload
    assert "status" not in payload
    assert len(methodology.identity_hash) == 64
    assert len(methodology.content_hash) == 64


@pytest.mark.parametrize(
    "overrides",
    [
        {"owner": "account"},
        {"artifact_type": "fee_config"},
        {"schema": "legacy"},
        {"permission": "active"},
    ],
)
def test_authority_and_permission_are_fixed(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _methodology(**overrides)


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("rate", 0.001),
        ("rate", True),
        ("rate", Decimal("NaN")),
        ("rate", Decimal("Infinity")),
        ("rate", Decimal("-0")),
        ("rate", Decimal("-0.01")),
        ("rounding_increment", Decimal("-0.00")),
    ],
)
def test_every_ratio_and_amount_requires_nonnegative_finite_exact_decimal(
    field_name: str, bad_value: object
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _fee_rule(**{field_name: bad_value})


@pytest.mark.parametrize(
    "rule",
    [
        _fee_rule(),
        _fee_rule(
            calculation_mode="fixed_amount",
            calculation_basis="fixed_per_order",
            rate=None,
            fixed_amount=Decimal("1"),
        ),
        _fee_rule(
            calculation_mode="rate_with_minimum",
            minimum_amount=Decimal("1"),
        ),
        _fee_rule(
            calculation_mode="rate_with_maximum",
            maximum_amount=Decimal("9"),
        ),
        _fee_rule(
            calculation_mode="rate_with_minimum_and_maximum",
            minimum_amount=Decimal("1"),
            maximum_amount=Decimal("9"),
        ),
    ],
)
def test_supported_calculation_modes_require_exact_value_shape(
    rule: PolicyBenchmarkCostTaxRule,
) -> None:
    assert rule.to_payload()["calculation_mode"] in {
        "rate",
        "fixed_amount",
        "rate_with_minimum",
        "rate_with_maximum",
        "rate_with_minimum_and_maximum",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"calculation_mode": "rate", "minimum_amount": Decimal("1")},
        {"calculation_mode": "fixed_amount", "rate": Decimal("0.1")},
        {"calculation_mode": "rate_with_minimum", "minimum_amount": None},
        {"calculation_mode": "rate_with_maximum", "maximum_amount": None},
        {
            "calculation_mode": "rate_with_minimum_and_maximum",
            "minimum_amount": Decimal("10"),
            "maximum_amount": Decimal("1"),
        },
    ],
)
def test_calculation_value_shape_cannot_fall_back_or_be_inferred(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _fee_rule(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"charge_kind": "unknown"},
        {"charge_event": "mystery"},
        {"trade_side": "hold"},
        {"calculation_basis": "net_amount"},
        {"recognition_timing": "unspecified"},
        {"charge_currency": "cny"},
        {"rate_precision_places": True},
        {"amount_precision_places": -1},
        {"rate_precision_places": 2},
        {
            "calculation_mode": "rate_with_minimum",
            "minimum_amount": Decimal("0.001"),
        },
        {"rounding_increment": Decimal("0.001")},
        {"rounding_mode": "implicit"},
    ],
)
def test_unknown_or_ambiguous_rule_semantics_fail_closed(
    overrides: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _fee_rule(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"charge_event": "trade", "trade_side": "not_applicable"},
        {
            "charge_event": "trade",
            "trade_side": "buy",
            "recognition_timing": "entitlement_recognition",
        },
        {
            "charge_event": "cash_dividend",
            "trade_side": "sell",
            "calculation_basis": "gross_cash_dividend_entitlement",
            "recognition_timing": "entitlement_recognition",
        },
        {
            "charge_event": "cash_dividend",
            "trade_side": "not_applicable",
            "calculation_basis": "gross_trade_notional",
            "recognition_timing": "entitlement_recognition",
        },
        {
            "charge_event": "cash_dividend",
            "trade_side": "not_applicable",
            "calculation_basis": "gross_cash_dividend_entitlement",
            "recognition_timing": "cash_payment",
        },
    ],
)
def test_event_side_basis_and_recognition_must_form_an_exact_rule(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _fee_rule(**overrides)


def test_sources_are_exact_ordered_complete_fee_and_tax_definitions() -> None:
    with pytest.raises(ValueError):
        _methodology(
            source_priority=(
                replace(_source(0, "fee", "broker-commission"), ordinal=1),
                _source(1, "tax", "cash-dividend-withholding"),
            )
        )
    with pytest.raises(ValueError):
        replace(
            _source(0, "fee", "broker-commission"),
            artifact_type="benchmark_tax_definition",
        )
    with pytest.raises(ValueError):
        _methodology(
            source_priority=(_source(0, "fee", "broker-commission"),),
            charge_rules=(_fee_rule(),),
        )
    with pytest.raises(ValueError):
        _methodology(
            source_priority=(
                _source(0, "fee", "broker-commission"),
                _source(1, "tax", "cash-dividend-withholding"),
            ),
            charge_rules=(_fee_rule(),),
        )
    with pytest.raises(ValueError):
        _methodology(
            charge_rules=(
                _fee_rule(),
                _tax_rule(charge_code="different-tax"),
            )
        )


def test_source_clock_and_validity_minimum_are_authoritative() -> None:
    with pytest.raises(ValueError):
        _methodology(
            source_priority=(
                _source(
                    0,
                    "fee",
                    "broker-commission",
                    recorded_at=RECORDED_AT + timedelta(seconds=1),
                ),
                _source(1, "tax", "cash-dividend-withholding"),
            )
        )
    with pytest.raises(ValueError):
        _methodology(valid_until=VALID_UNTIL - timedelta(seconds=1))
    with pytest.raises(ValueError):
        _methodology(recorded_at=RECORDED_AT.replace(tzinfo=None))


def test_fail_closed_and_duplicate_prevention_policies_cannot_be_weakened() -> None:
    methodology = _methodology()
    payload = methodology.to_payload()

    assert payload["unknown_asset_policy"] == "fail_closed"
    assert payload["unknown_fee_policy"] == "fail_closed"
    assert payload["unknown_tax_policy"] == "fail_closed"
    assert payload["missing_source_policy"] == "fail_closed"
    assert payload["source_failure_policy"] == "block"
    assert payload["estimation_policy"] == "prohibited"
    assert payload["silent_zero_policy"] == "prohibited"
    assert payload["duplicate_charge_policy"] == "block"
    assert payload["cash_dividend_charge_policy"] == "entitlement_once"
    assert payload["cash_dividend_payment_policy"] == "settlement_only_no_second_charge"
    assert payload["corporate_action_charge_policy"] == "exact_event_once"
    assert payload["already_net_amount_policy"] == "block"

    for field_name in (
        "unknown_asset_policy",
        "unknown_fee_policy",
        "unknown_tax_policy",
        "missing_source_policy",
    ):
        with pytest.raises(ValueError):
            _methodology(**{field_name: "assume_zero"})
    with pytest.raises(ValueError):
        _methodology(duplicate_charge_policy="allow")


def test_duplicate_charge_coverage_is_rejected() -> None:
    duplicate_source = replace(
        _source(2, "tax", "cash-dividend-withholding"),
        artifact_id="charge-duplicate",
        content_hash="f" * 64,
    )
    with pytest.raises(ValueError):
        _methodology(
            source_priority=(
                _source(0, "fee", "broker-commission"),
                _source(1, "tax", "cash-dividend-withholding"),
                duplicate_source,
            ),
            charge_rules=(
                _fee_rule(),
                _tax_rule(),
                replace(
                    _tax_rule(),
                    ordinal=2,
                    source_ordinal=2,
                    charge_event="corporate_action",
                    calculation_basis="gross_corporate_action_cash_entitlement",
                    recognition_timing="effective_date_recognition",
                ),
            ),
        )


def test_explicit_zero_is_sealed_but_missing_or_unknown_never_becomes_zero() -> None:
    explicit_zero = _fee_rule(rate=Decimal("0.0000"))
    methodology = _methodology(charge_rules=(explicit_zero, _tax_rule()))

    assert methodology.to_payload()["charge_rules"][0]["rate"] == "0"  # type: ignore[index]
    assert methodology.silent_zero_allowed is False
    assert methodology.automatic_fallback_allowed is False


def test_decimal_spelling_is_canonical_but_content_changes_are_detected() -> None:
    first = _methodology()
    second = _methodology(
        charge_rules=(
            _fee_rule(rate=Decimal("3E-4"), rounding_increment=Decimal("1E-2")),
            _tax_rule(rate=Decimal("1E-1"), rounding_increment=Decimal("1E-2")),
        )
    )
    changed = _methodology(charge_rules=(_fee_rule(rate=Decimal("0.0004")), _tax_rule()))

    assert first.content_hash == second.content_hash
    assert first.content_hash != changed.content_hash
    with pytest.raises(ValueError):
        _methodology(content_hash="0" * 64)
    with pytest.raises(ValueError):
        _methodology(identity_hash="0" * 64)


def test_knowability_is_half_open_and_requires_aware_time() -> None:
    methodology = _methodology()

    assert methodology.is_knowable_at(RECORDED_AT)
    assert methodology.is_knowable_at(VALID_UNTIL - timedelta(microseconds=1))
    assert not methodology.is_knowable_at(VALID_UNTIL)
    with pytest.raises(ValueError):
        methodology.is_knowable_at(RECORDED_AT.replace(tzinfo=None))
