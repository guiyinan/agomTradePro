"""Public financial rows preserve the native/legacy numeric schema boundary."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
)
from apps.equity.infrastructure import fundamentals_published_fact_mappers as fact_mappers
from apps.equity.infrastructure.fundamentals_published_fact_mappers import (
    parse_public_financial_fact,
)

_BASE_ROW: dict[str, object] = {
    "asset_code": "000001.SZ",
    "period_end": "2026-06-30",
    "period_type": "semi_annual",
    "metric_code": "roe",
    "value": "12.3400",
    "unit": "%",
    "source": "akshare",
    "report_date": "2026-08-15",
    "available_at": "2026-08-17T01:30:00+00:00",
    "fetched_at": "2026-09-13T04:05:06.789000+00:00",
    "extra": {"retained": ["legacy", 1]},
}


def _native_evidence() -> NativeFinancialMetricObservation:
    """Return a synthetic, internally consistent observation for mapper tests."""

    contract = FinancialMetricSourceContract(
        provider="akshare",
        dataset_key="equity.financial.fact",
        metric_code="roe",
        source_field="ROEJQ",
        source_unit="%",
        canonical_unit="%",
        scale_numerator=1,
        scale_denominator=1,
        contract_version="test-native-1",
        origin="native",
    )
    return NativeFinancialMetricObservation.from_raw_value(
        contract=contract,
        raw_value="1.775599913526",
        source_field="ROEJQ",
        body_sha256="a" * 64,
        native_row_id="source-row-1",
    )


def _native_row() -> dict[str, object]:
    """Build the actual public v2 row shape without a provider or database."""

    evidence = _native_evidence()
    return {
        **_BASE_ROW,
        "value": evidence.canonical_value,
        "numeric_schema": "native-decimal-v2",
        "numeric_evidence": evidence.to_dict(),
    }


def test_legacy_numeric_string_keeps_the_existing_v1_wire_golden() -> None:
    """A plain legacy string remains compatible when no native marker exists."""

    fact = parse_public_financial_fact(_BASE_ROW)

    assert fact is not None
    assert fact.numeric_schema == "legacy-decimal-v1"
    assert type(fact.value) is float
    assert fact.to_dict() == {
        "asset_code": "000001.SZ",
        "period_end": "2026-06-30",
        "period_type": "semi_annual",
        "metric_code": "roe",
        "value": 12.34,
        "unit": "%",
        "source": "akshare",
        "report_date": "2026-08-15",
        "available_at": "2026-08-17T01:30:00+00:00",
        "fetched_at": "2026-09-13T04:05:06.789000+00:00",
        "extra": {"retained": ["legacy", 1]},
        "source_evidence": None,
        "decision_evidence": None,
    }


def test_native_canonical_string_keeps_the_v2_schema_and_decimal() -> None:
    """The real v2 public shape still reconstructs the exact Decimal value."""

    row = _native_row()
    fact = parse_public_financial_fact(row)

    assert fact is not None
    assert fact.numeric_schema == "native-decimal-v2"
    assert type(fact.value) is Decimal
    assert fact.value == Decimal("1.775599913526")
    assert fact.to_dict()["value"] == "1.775599913526"
    assert fact.to_dict()["numeric_schema"] == "native-decimal-v2"
    assert fact.to_dict()["numeric_evidence"] == row["numeric_evidence"]


@pytest.mark.parametrize(
    "changes",
    [
        {"numeric_evidence": _native_evidence().to_dict()},
        {"numeric_evidence": None},
        {"exact_value_text": None},
        {"numeric_schema": "legacy-decimal-v1", "exact_value_text": "1.775599913526"},
        {"exact_value_text": "1.775599913526"},
        {
            "numeric_schema": "legacy-decimal-v1",
            "numeric_evidence": _native_evidence().to_dict(),
        },
        {
            "numeric_schema": "legacy-decimal-v1",
            "numeric_evidence": None,
        },
        {
            "numeric_schema": "legacy-decimal-v1",
            "exact_value_text": None,
        },
    ],
)
def test_unmarked_or_legacy_native_fields_fail_closed_before_float_parse(
    changes: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Native-only field evidence cannot be demoted through ``safe_float``."""

    def unexpected_float_parse(value: object, **kwargs: object) -> float | None:
        raise AssertionError(f"safe_float reached for conflicting native payload: {value!r}")

    monkeypatch.setattr(fact_mappers, "safe_float", unexpected_float_parse)
    row = _BASE_ROW | changes

    assert parse_public_financial_fact(row) is None


def test_legacy_numeric_string_remains_accepted_with_explicit_legacy_schema() -> None:
    """Explicit legacy rows without native-only fields retain existing coercion."""

    row = _BASE_ROW | {"numeric_schema": "legacy-decimal-v1"}
    fact = parse_public_financial_fact(row)

    assert fact is not None
    assert fact.numeric_schema == "legacy-decimal-v1"
    assert type(fact.value) is float
    assert fact.value == 12.34


@pytest.mark.parametrize("stored_value", [None, "1.775599913526"])
def test_public_native_row_rejects_storage_only_value_field(stored_value: object) -> None:
    """Storage-only fields cannot be accepted as an alternate public v2 shape."""

    row = _native_row() | {"exact_value_text": stored_value}
    assert parse_public_financial_fact(row) is None
