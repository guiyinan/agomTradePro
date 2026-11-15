"""Exact native financial values retain legacy payload compatibility."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
)


def _native() -> NativeFinancialMetricObservation:
    return NativeFinancialMetricObservation.from_raw_value(
        contract=FinancialMetricSourceContract(
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
        ),
        raw_value="1.775599913526",
        source_field="ROEJQ",
        body_sha256="a" * 64,
        native_row_id="source-row-1",
    )


def _fact() -> FinancialFact:
    return FinancialFact(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type=FinancialPeriodType.SEMI_ANNUAL,
        metric_code="roe",
        value=12.34,
        unit="%",
        source="akshare",
        report_date=date(2026, 8, 15),
        available_at=datetime(2026, 8, 17, 1, 30, tzinfo=UTC),
        fetched_at=datetime(2026, 9, 13, 4, 5, 6, 789000, tzinfo=UTC),
        extra={"retained": ["legacy", 1]},
    )


def test_legacy_payload_matches_before_migration_golden() -> None:
    """Expected payload was captured from b96a before numeric-schema changes."""
    assert _fact().to_dict() == {
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


def test_native_exact_decimal_has_explicit_lossless_wire_schema() -> None:
    native = _native()
    fact = replace(
        _fact(),
        value=Decimal(native.canonical_value),
        numeric_schema="native-decimal-v2",
        numeric_evidence=native,
    )
    assert type(fact.value) is Decimal
    assert fact.to_dict()["value"] == "1.775599913526"
    assert fact.to_dict()["numeric_schema"] == "native-decimal-v2"
    assert fact.to_dict()["numeric_evidence"] == native.to_dict()


@pytest.mark.parametrize("value", [1.775599913526, True, Decimal("NaN"), Decimal("Infinity")])
def test_native_schema_rejects_inexact_or_nonfinite_value(value: object) -> None:
    with pytest.raises(ValueError):
        replace(
            _fact(), value=value, numeric_schema="native-decimal-v2", numeric_evidence=_native()
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"value": Decimal("1.7756")},
        {"metric_code": "net_profit"},
        {"unit": "元"},
        {"source": "different-provider"},
        {"numeric_evidence": None},
        {"numeric_schema": "unknown"},
    ],
)
def test_native_fact_rejects_substituted_numeric_subject(changes: dict[str, object]) -> None:
    fact = replace(
        _fact(),
        value=Decimal("1.775599913526"),
        numeric_schema="native-decimal-v2",
        numeric_evidence=_native(),
    )
    with pytest.raises(ValueError):
        replace(fact, **changes)


def test_legacy_cannot_silently_accept_decimal_or_attach_native_evidence() -> None:
    with pytest.raises(ValueError):
        replace(_fact(), value=Decimal("12.34"))
    with pytest.raises(ValueError):
        replace(_fact(), numeric_evidence=_native())
