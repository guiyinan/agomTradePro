"""Tests for strict versioned deferred-dividend policy JSON decoding."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import cast

import pytest

import apps.simulated_trading.application.corporate_action_tax_policy as tax_policy_module
from apps.simulated_trading.application.corporate_action_tax_policy import (
    CorporateActionTaxPolicyDecodeError,
    DeferredDividendTaxPolicyJSON,
    decode_deferred_dividend_tax_policy,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxPolicy,
    TaxRoundingMode,
)
from core.exceptions import BusinessLogicError


def _policy_json() -> DeferredDividendTaxPolicyJSON:
    """Build one complete explicit policy candidate without asserting its source."""

    return {
        "schema_version": "simulated_trading.deferred_dividend_tax_policy.v1",
        "policy_id": "statutory-dividend-tax-policy",
        "version": "rule-version-2026-a",
        "effective_from": "2025-01-01",
        "effective_through": "2027-12-31",
        "source_identity": "statutory-source-fixture-2015-101",
        "source_sha256": "a" * 64,
        "bands": [
            {
                "band_id": "short-period",
                "maximum_holding_months": 1,
                "taxable_dividend_ratio": "1",
                "withholding_rate": "0.2",
            },
            {
                "band_id": "long-period",
                "maximum_holding_months": None,
                "taxable_dividend_ratio": "0",
                "withholding_rate": "0",
            },
        ],
        "currency_quantum": "0.01",
        "rounding_mode": "ROUND_HALF_UP",
    }


def _mutable_policy_json() -> dict[str, object]:
    """Copy the typed fixture into an adversarial JSON object for negative cases."""

    return cast(dict[str, object], deepcopy(_policy_json()))


def _band(payload: dict[str, object], index: int = 0) -> dict[str, object]:
    """Return one mutable nested band from an untrusted JSON-shaped object."""

    bands = cast(list[object], payload["bands"])
    return cast(dict[str, object], bands[index])


def test_decoder_preserves_every_explicit_policy_field() -> None:
    policy = decode_deferred_dividend_tax_policy(_policy_json())

    assert type(policy) is DeferredDividendTaxPolicy
    assert policy.policy_id == "statutory-dividend-tax-policy"
    assert policy.version == "rule-version-2026-a"
    assert policy.effective_from == date(2025, 1, 1)
    assert policy.effective_through == date(2027, 12, 31)
    assert policy.source_identity == "statutory-source-fixture-2015-101"
    assert policy.source_sha256 == "a" * 64
    assert policy.bands[0].maximum_holding_months == 1
    assert policy.bands[0].taxable_dividend_ratio == Decimal("1")
    assert policy.bands[0].withholding_rate == Decimal("0.2")
    assert policy.bands[-1].maximum_holding_months is None
    assert policy.currency_quantum == Decimal("0.01")
    assert policy.rounding_mode is TaxRoundingMode.HALF_UP
    assert len(policy.policy_sha256) == 64


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "policy_id",
        "version",
        "effective_from",
        "effective_through",
        "source_identity",
        "source_sha256",
        "bands",
        "currency_quantum",
        "rounding_mode",
    ],
)
def test_decoder_requires_every_top_level_field(field: str) -> None:
    payload = _mutable_policy_json()
    del payload[field]

    with pytest.raises(CorporateActionTaxPolicyDecodeError) as captured:
        decode_deferred_dividend_tax_policy(payload)

    assert isinstance(captured.value, BusinessLogicError)
    assert captured.value.code == "CORPORATE_ACTION_TAX_POLICY_DECODE_INVALID"


def test_decoder_rejects_unknown_top_level_fields() -> None:
    payload = _mutable_policy_json()
    payload["implicit_default_rate"] = "0.2"

    with pytest.raises(CorporateActionTaxPolicyDecodeError):
        decode_deferred_dividend_tax_policy(payload)


@pytest.mark.parametrize(
    "field",
    [
        "band_id",
        "maximum_holding_months",
        "taxable_dividend_ratio",
        "withholding_rate",
    ],
)
def test_decoder_requires_every_nested_band_field(field: str) -> None:
    payload = _mutable_policy_json()
    del _band(payload)[field]

    with pytest.raises(CorporateActionTaxPolicyDecodeError):
        decode_deferred_dividend_tax_policy(payload)


def test_decoder_rejects_unknown_nested_band_fields() -> None:
    payload = _mutable_policy_json()
    _band(payload)["tax_code"] = "unused"

    with pytest.raises(CorporateActionTaxPolicyDecodeError):
        decode_deferred_dividend_tax_policy(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("effective_from", "2025-1-1"),
        ("effective_through", "2028-W01-1"),
        ("effective_from", None),
        ("currency_quantum", 0.01),
        ("rounding_mode", "ROUND_HALF_UP "),
        ("schema_version", "simulated_trading.deferred_dividend_tax_policy.v2"),
    ],
)
def test_decoder_rejects_noncanonical_or_coerced_top_level_values(
    field: str,
    value: object,
) -> None:
    payload = _mutable_policy_json()
    payload[field] = value

    with pytest.raises(CorporateActionTaxPolicyDecodeError):
        decode_deferred_dividend_tax_policy(payload)


@pytest.mark.parametrize("invalid_decimal", [0.2, 1, "1e-2", "NaN", "+1"])
def test_decoder_rejects_non_string_or_non_plain_decimal_rates(
    invalid_decimal: object,
) -> None:
    payload = _mutable_policy_json()
    _band(payload)["withholding_rate"] = invalid_decimal

    with pytest.raises(CorporateActionTaxPolicyDecodeError):
        decode_deferred_dividend_tax_policy(payload)


def test_decoder_rejects_boolean_holding_threshold() -> None:
    payload = _mutable_policy_json()
    _band(payload)["maximum_holding_months"] = True

    with pytest.raises(CorporateActionTaxPolicyDecodeError):
        decode_deferred_dividend_tax_policy(payload)


def test_decoder_rejects_unsupported_holding_month_threshold() -> None:
    payload = _mutable_policy_json()
    _band(payload)["maximum_holding_months"] = 10**10

    with pytest.raises(CorporateActionTaxPolicyDecodeError):
        decode_deferred_dividend_tax_policy(payload)


def test_decoder_rejects_currency_quantum_beyond_supported_scale() -> None:
    payload = _mutable_policy_json()
    payload["currency_quantum"] = "0.0000000000001"

    with pytest.raises(CorporateActionTaxPolicyDecodeError):
        decode_deferred_dividend_tax_policy(payload)


def test_decoder_rejects_overlong_decimal_before_decimal_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _mutable_policy_json()
    payload["currency_quantum"] = "0." + ("0" * 10_000) + "1"
    decimal_constructor = tax_policy_module.Decimal

    def reject_overlong_construction(text: str) -> Decimal:
        if len(text) > 32:
            pytest.fail("overlong decimal reached Decimal construction")
        return decimal_constructor(text)

    monkeypatch.setattr(tax_policy_module, "Decimal", reject_overlong_construction)

    with pytest.raises(CorporateActionTaxPolicyDecodeError):
        decode_deferred_dividend_tax_policy(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("taxable_dividend_ratio", "1.01"),
        ("withholding_rate", "-0.01"),
    ],
)
def test_decoder_maps_invalid_domain_band_rules_to_business_error(
    field: str,
    value: str,
) -> None:
    payload = _mutable_policy_json()
    _band(payload)[field] = value

    with pytest.raises(CorporateActionTaxPolicyDecodeError) as captured:
        decode_deferred_dividend_tax_policy(payload)

    assert isinstance(captured.value, BusinessLogicError)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_sha256", "not-a-sha256"),
        ("effective_through", "2024-12-31"),
    ],
)
def test_decoder_maps_invalid_domain_source_and_date_rules(
    field: str,
    value: str,
) -> None:
    payload = _mutable_policy_json()
    payload[field] = value

    with pytest.raises(CorporateActionTaxPolicyDecodeError):
        decode_deferred_dividend_tax_policy(payload)


def test_decoder_requires_final_unbounded_band_and_allows_explicit_open_dates() -> None:
    payload = _mutable_policy_json()
    payload["effective_through"] = None
    _band(payload, 1)["maximum_holding_months"] = None

    decoded = decode_deferred_dividend_tax_policy(payload)

    assert decoded.effective_through is None
    assert decoded.bands[-1].maximum_holding_months is None

    no_unbounded_band = _mutable_policy_json()
    _band(no_unbounded_band, 1)["maximum_holding_months"] = 24
    with pytest.raises(CorporateActionTaxPolicyDecodeError):
        decode_deferred_dividend_tax_policy(no_unbounded_band)
