"""Pre-migration golden identities and strict native financial decoding."""

from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from apps.data_center.domain.financial_numeric_evidence import NativeFinancialMetricObservation
from apps.data_center.infrastructure.financial_fact_repository import FinancialFactRepository
from apps.data_center.infrastructure.financial_numeric_storage import (
    decode_financial_numeric_row,
    decode_native_financial_numeric_evidence,
)
from apps.data_center.infrastructure.models import FinancialFactModel
from apps.data_center.infrastructure.publication_fact_evidence import canonical_fact_content_hash
from apps.data_center.infrastructure.publication_fact_legacy_payload import financial_payload_hash
from apps.equity.infrastructure.fundamentals_published_fact_mappers import (
    parse_public_financial_fact,
)
from tests.unit.data_center.test_financial_native_decimal_fact import _fact, _native


@pytest.mark.parametrize(
    "number,value,row_hash,payload_hash",
    [
        (
            1,
            "12.3400",
            "9cdc71c9afeeb17dfddfb68976e37b4f497357c9f16106398b31e9af0b8f76cf",
            "dddf800d513ea9aba922a03ad5e3a0e0fe5ba546ca93ca46a0fc68be838fa6c1",
        ),
        (
            2,
            "0.0000",
            "d6a25e2c2466f70f66eb772929d3654835aa8f662cd6692bac1924f83711d838",
            "86fff92994f5a391ae2af490b795dc1a215f912c0ae16e35c665a1a201a79ef1",
        ),
        (
            3,
            "-0.0100",
            "d1b2f68cbc8d5f803367615ff437eee6c72cab0bf653173599b1dfe199d5976b",
            "fa72f77a5feb71868eb8e84ffb275730bec7820a668b8b5b4df350b84d057ae4",
        ),
    ],
)
@pytest.mark.parametrize("orm_value_is_text", [False, True])
def test_legacy_frozen_hashes_match_before_migration(
    number: int, value: str, row_hash: str, payload_hash: str, orm_value_is_text: bool
) -> None:
    """Constants were captured independently from b96a before adding columns."""
    row = FinancialFactModel(
        id=number,
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type="semi_annual",
        metric_code="roe",
        value=value if orm_value_is_text else Decimal(value),
        unit="%",
        source="akshare",
        report_date=date(2026, 8, 15),
        fetched_at=datetime(2026, 9, 13, 4, 5, 6, 789000, tzinfo=UTC),
        extra={"retained": ["legacy", number]},
        decision_evidence={},
        contract_version="1.0",
        schema_version="1.0",
        source_record_id="",
        raw_payload_hash="",
        quality_status="accepted",
        revision_number=number,
        ingested_run_id=UUID("11111111-2222-3333-4444-555555555555"),
        announced_at=None,
        available_at=datetime(2026, 8, 17, 1, 30, tzinfo=UTC),
    )
    assert canonical_fact_content_hash(row) == row_hash
    assert financial_payload_hash(row) == payload_hash
    assert FinancialFactRepository._from_model(row).to_dict()["value"] == float(value)


@pytest.mark.parametrize(
    "value", [None, True, "", "NaN", "Infinity", "-Infinity", "not-a-number", "1e10000"]
)
def test_legacy_numeric_orm_rejects_invalid_or_nonfinite_values(value: object) -> None:
    """Legacy string compatibility never supplies a default for an invalid value."""
    row = FinancialFactModel(value=value)
    with pytest.raises(ValueError):
        decode_financial_numeric_row(row)


def test_native_wire_roundtrip_and_consumer_mapper_keep_exact_digits() -> None:
    from dataclasses import replace

    evidence = _native()
    restored = decode_native_financial_numeric_evidence(evidence.to_dict())
    assert restored == evidence
    fact = replace(
        _fact(),
        value=Decimal(evidence.canonical_value),
        numeric_schema="native-decimal-v2",
        numeric_evidence=evidence,
    )
    parsed = parse_public_financial_fact(fact.to_dict())
    assert parsed is not None
    assert type(parsed.value) is Decimal
    assert parsed.value == Decimal("1.775599913526")
    assert parsed.to_dict()["value"] == "1.775599913526"


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("source_decimal_places", True),
        ("source_value", "1.7756"),
        ("canonical_value", "1.7756"),
        ("production_ready", True),
        ("evidence_only", 1),
        ("must_not_use_for_decision", False),
        ("contract_hash", "b" * 64),
        ("schema", "unknown"),
        ("unexpected", "extra"),
    ],
)
def test_native_wire_rejects_changed_fields(field: str, replacement: object) -> None:
    payload = deepcopy(_native().to_dict())
    payload[field] = replacement
    with pytest.raises(ValueError):
        NativeFinancialMetricObservation.from_payload(payload)


def test_native_consumer_rejects_binary_float_even_when_numerically_close() -> None:
    from dataclasses import replace

    fact = replace(
        _fact(),
        value=Decimal("1.775599913526"),
        numeric_schema="native-decimal-v2",
        numeric_evidence=_native(),
    )
    payload = fact.to_dict()
    payload["value"] = 1.775599913526
    assert parse_public_financial_fact(payload) is None
