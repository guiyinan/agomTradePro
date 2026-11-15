"""Contract and native exact-value evidence tests without database dependencies."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from typing import Literal, cast

import pytest

from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
)


def _contract(
    *,
    source_unit: str = "source_unit",
    canonical_unit: str = "canonical_unit",
    scale_numerator: int = 1,
    scale_denominator: int = 1,
) -> FinancialMetricSourceContract:
    """Build a complete test-only native contract with every scale explicit."""

    return FinancialMetricSourceContract(
        provider="test_provider",
        dataset_key="test.dataset",
        metric_code="test_metric",
        source_field="RAW_FIELD",
        source_unit=source_unit,
        canonical_unit=canonical_unit,
        scale_numerator=scale_numerator,
        scale_denominator=scale_denominator,
        contract_version="test.v1",
        origin="native",
    )


def _observation(
    *,
    raw_value: object = Decimal("12.345"),
    source_field: str = "RAW_FIELD",
    body_sha256: str = "a" * 64,
    native_row_id: str = "test_provider:asset:period",
    contract: FinancialMetricSourceContract | None = None,
) -> NativeFinancialMetricObservation:
    """Build one test observation through the strict raw-value boundary."""

    selected_contract = contract or _contract()
    return NativeFinancialMetricObservation.from_raw_value(
        contract=selected_contract,
        raw_value=raw_value,
        source_field=source_field,
        body_sha256=body_sha256,
        native_row_id=native_row_id,
    )


def test_contract_identity_binds_every_explicit_source_interpretation() -> None:
    """A unit, scale, provider, field or version change creates a new identity."""

    original = _contract()
    assert original.identity.startswith("financial-metric-source-contract.v1:test.v1:")
    assert len(original.content_hash) == 64
    assert replace(original, provider="other_provider").content_hash != original.content_hash
    assert replace(original, dataset_key="other.dataset").content_hash != original.content_hash
    assert replace(original, metric_code="other_metric").content_hash != original.content_hash
    assert replace(original, source_field="OTHER_FIELD").content_hash != original.content_hash
    assert replace(original, source_unit="other_source_unit").content_hash != original.content_hash
    assert (
        replace(original, canonical_unit="other_canonical_unit").content_hash
        != original.content_hash
    )
    assert replace(original, scale_numerator=2).content_hash != original.content_hash
    assert replace(original, scale_denominator=2).content_hash != original.content_hash
    assert replace(original, contract_version="test.v2").content_hash != original.content_hash


def test_contract_serializes_all_fields_and_explicit_scale() -> None:
    """The contract hash input is also available as a complete JSON-safe value."""

    contract = _contract(scale_numerator=1, scale_denominator=100)
    assert contract.to_dict() == {
        "canonical_unit": "canonical_unit",
        "contract_version": "test.v1",
        "dataset_key": "test.dataset",
        "metric_code": "test_metric",
        "origin": "native",
        "provider": "test_provider",
        "scale_denominator": 100,
        "scale_numerator": 1,
        "schema": "financial-metric-source-contract.v1",
        "source_field": "RAW_FIELD",
        "source_unit": "source_unit",
    }
    field_name = "metric_code"
    with pytest.raises(FrozenInstanceError):
        setattr(contract, field_name, "changed")


@pytest.mark.parametrize("unit", ["", "unknown", "native", "catalog", " 元", "unit\x00"])
def test_contract_rejects_missing_placeholder_or_malformed_units(unit: str) -> None:
    """An unsupported unit cannot enter an exact native source contract."""

    with pytest.raises(ValueError):
        _contract(source_unit=unit)
    with pytest.raises(ValueError):
        _contract(canonical_unit=unit)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("scale_numerator", True),
        ("scale_numerator", 0),
        ("scale_numerator", -1),
        ("scale_denominator", False),
        ("scale_denominator", 0),
        ("scale_denominator", -1),
        ("scale_denominator", 1.5),
    ],
)
def test_contract_rejects_implicit_or_invalid_scale(name: str, value: object) -> None:
    """Scale must be explicitly supplied as a positive integer ratio."""

    with pytest.raises((TypeError, ValueError)):
        replace(_contract(), **{name: value})


def test_contract_rejects_derived_origin_and_unbounded_identity_text() -> None:
    """This contract type only represents explicit native provider fields."""

    with pytest.raises(ValueError, match="native"):
        replace(_contract(), origin=cast(Literal["native"], "derived"))
    with pytest.raises(ValueError):
        replace(_contract(), source_field="RAW FIELD")
    with pytest.raises(ValueError):
        replace(_contract(), metric_code=" padded ")
    with pytest.raises(ValueError):
        replace(_contract(), metric_code="metric:other")


def test_observation_preserves_exact_native_decimal_and_exact_scale() -> None:
    """The source value and converted value remain finite decimal strings."""

    contract = _contract(scale_numerator=1, scale_denominator=100)
    observation = _observation(raw_value=Decimal("123.4500"), contract=contract)
    assert observation.source_value_text == "123.4500"
    assert observation.source_value == "123.45"
    assert observation.source_decimal_places == 4
    assert observation.canonical_value == "1.2345"
    assert observation.contract_identity == contract.identity
    assert observation.origin == "native"


@pytest.mark.parametrize(
    ("raw_value", "expected_text", "expected_places"),
    [
        (123, "123", 0),
        ("-0.00120", "-0.0012", 5),
        (Decimal("1E+3"), "1000", 0),
        (Decimal("0E-5"), "0", 5),
    ],
)
def test_observation_accepts_exact_json_decimal_integer_or_plain_text(
    raw_value: object,
    expected_text: str,
    expected_places: int,
) -> None:
    """Exact supported boundary types preserve numeric value and source scale."""

    observation = _observation(raw_value=raw_value)
    assert observation.source_value == expected_text
    assert observation.source_decimal_places == expected_places
    assert observation.canonical_value == expected_text


def test_observation_accepts_values_at_the_128_character_fixed_decimal_bound() -> None:
    """Ordinary finite values fit the explicit canonical text length bound."""

    large = _observation(raw_value=Decimal("1E+127"))
    small = _observation(raw_value=Decimal("1E-126"))
    assert len(large.source_value_text) == 128
    assert len(small.source_value_text) == 128


def test_observation_rejects_extreme_decimal_exponents_before_formatting() -> None:
    """Huge positive and negative exponents fail before fixed text expansion."""

    with pytest.raises(ValueError, match="length limit"):
        _observation(raw_value=Decimal("1E+1000000"))
    with pytest.raises(ValueError, match="length limit"):
        _observation(raw_value=Decimal("1E-1000000"))
    with pytest.raises(ValueError, match="length limit"):
        _observation(raw_value=Decimal("0E-1000000"))


def test_observation_rejects_large_integers_before_decimal_string_conversion() -> None:
    """An unbounded JSON integer is rejected before converting it to text."""

    with pytest.raises(ValueError, match="length limit"):
        _observation(raw_value=10**5000)


@pytest.mark.parametrize(
    "raw_value",
    [None, True, False, 0.1, "", " 1", "+1", "1e-3", "NaN", "Infinity", "1,000"],
)
def test_observation_rejects_missing_float_or_noncanonical_raw_values(raw_value: object) -> None:
    """None, binary floats and malformed values never become zero or rounded data."""

    with pytest.raises(ValueError):
        _observation(raw_value=raw_value)


def test_observation_rejects_nonfinite_decimal_instances() -> None:
    """Decimal NaN and infinities do not become numeric observations."""

    with pytest.raises(ValueError, match="finite"):
        _observation(raw_value=Decimal("NaN"))
    with pytest.raises(ValueError, match="finite"):
        _observation(raw_value=Decimal("Infinity"))


@pytest.mark.parametrize("raw_value", ["١٢.٣", "１２.３"])
def test_observation_rejects_non_ascii_decimal_digits(raw_value: str) -> None:
    """Source numeric text is not Unicode-normalized or silently rewritten."""

    with pytest.raises(ValueError, match="ASCII"):
        _observation(raw_value=raw_value)


def test_observation_performs_large_exact_decimal_conversion_without_context_rounding() -> None:
    """The exact integer-ratio conversion does not use Decimal context precision."""

    contract = _contract(scale_numerator=20, scale_denominator=1)
    raw_value = Decimal("123456789012345678901234567890.123456789012")
    observation = _observation(raw_value=raw_value, contract=contract)
    assert observation.canonical_value == "2469135780246913578024691357802.46913578024"


def test_observation_rejects_a_nonterminating_decimal_scale_instead_of_rounding() -> None:
    """A rational result without a finite decimal representation is blocked."""

    contract = _contract(scale_numerator=1, scale_denominator=3)
    with pytest.raises(ValueError, match="terminating"):
        _observation(raw_value=Decimal("1"), contract=contract)


@pytest.mark.parametrize(
    ("source_field", "body_sha256", "native_row_id"),
    [
        ("OTHER_FIELD", "a" * 64, "test_provider:asset:period"),
        ("RAW_FIELD", "A" * 64, "test_provider:asset:period"),
        ("RAW_FIELD", "a" * 64, ""),
        ("RAW_FIELD", "a" * 64, " padded "),
    ],
)
def test_observation_rejects_field_body_or_row_identity_mismatch(
    source_field: str,
    body_sha256: str,
    native_row_id: str,
) -> None:
    """Every observation is bound to its exact contract field and source row."""

    with pytest.raises(ValueError):
        _observation(
            source_field=source_field,
            body_sha256=body_sha256,
            native_row_id=native_row_id,
        )


def test_observation_rejects_tampered_value_precision_or_contract() -> None:
    """Direct construction cannot claim rounded values under exact evidence."""

    observation = _observation(raw_value=Decimal("12.3456"))
    with pytest.raises(ValueError, match="does not match"):
        replace(observation, canonical_value="12.35")
    with pytest.raises(ValueError, match="canonical form"):
        replace(observation, source_value="12.346")
    with pytest.raises(ValueError, match="field"):
        replace(observation, source_field="OTHER_FIELD")
    with pytest.raises(ValueError, match="contract"):
        replace(observation, contract=replace(_contract(), metric_code="other_metric"))
    with pytest.raises(ValueError, match="precision"):
        replace(observation, source_decimal_places=3)
    with pytest.raises(ValueError, match="canonical decimal form"):
        replace(observation, canonical_value="12.345600")
    with pytest.raises(ValueError, match="contract"):
        replace(observation, contract_hash="0" * 64)


def test_observation_rejects_an_untyped_contract_at_each_boundary() -> None:
    """Runtime values from an ORM or JSON boundary must be narrowed first."""

    observation = _observation()
    invalid_contract = cast(FinancialMetricSourceContract, object())
    with pytest.raises(TypeError, match="FinancialMetricSourceContract"):
        replace(observation, contract=invalid_contract)
    with pytest.raises(TypeError, match="FinancialMetricSourceContract"):
        NativeFinancialMetricObservation.from_raw_value(
            contract=invalid_contract,
            raw_value=Decimal("1"),
            source_field="RAW_FIELD",
            body_sha256="a" * 64,
            native_row_id="row-1",
        )


def test_observation_serialization_and_hash_bind_source_and_contract() -> None:
    """Serialized evidence includes body, row, exact values and full contract identity."""

    observation = _observation(raw_value=Decimal("12.345"))
    payload = observation.to_dict()
    assert payload["schema"] == "financial-native-metric-observation.v1"
    assert payload["origin"] == "native"
    assert payload["body_sha256"] == "a" * 64
    assert payload["native_row_id"] == "test_provider:asset:period"
    assert payload["source_field"] == "RAW_FIELD"
    assert payload["source_value_text"] == "12.345"
    assert payload["source_value"] == "12.345"
    assert payload["canonical_value"] == "12.345"
    assert payload["evidence_only"] is True
    assert payload["production_ready"] is False
    assert payload["must_not_use_for_decision"] is True
    assert payload["contract"] == observation.contract.to_dict()
    assert payload["contract_identity"] == observation.contract.identity
    assert payload["contract_hash"] == observation.contract.content_hash
    assert len(observation.content_hash) == 64
    assert observation.identity.startswith("financial-native-metric-observation.v1:")
    assert replace(observation, native_row_id="other_provider:asset:period").content_hash != (
        observation.content_hash
    )
