from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.data_center.application.quote_metric_normalization import (
    normalize_quote_snapshot_change_pct,
)
from apps.data_center.application.sync_quote_use_case import SyncQuoteUseCase
from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    QuoteMetricSourceContract,
)
from apps.data_center.domain.entities import QuoteChangePctCandidate, QuoteSnapshot
from apps.data_center.infrastructure.quote_snapshot_orm_mapper import (
    quote_snapshot_from_model,
    quote_snapshots_to_models,
)
from apps.data_center.infrastructure.quote_snapshot_repository import QuoteSnapshotRepository

SNAPSHOT_AT = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)


def _source_contract(*, action_basis: str = "vendor_basis_unverified") -> QuoteMetricSourceContract:
    return QuoteMetricSourceContract(
        provider_source="vendor-main",
        source_field="pct",
        origin="vendor_reported",
        source_unit="hundredth_percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=100,
        reference_session="source_quote_observation",
        action_basis=action_basis,
    )


def _contract(
    source_contract: QuoteMetricSourceContract,
    *,
    contract_version: str = "2.0",
    schema_version: str = "2.0",
) -> DatasetContract:
    return DatasetContract(
        key=DatasetKey("equity.quote.snapshot", contract_version, schema_version),
        owner="data-platform",
        frequency="intraday",
        decision_critical=True,
        freshness_seconds=14_400,
        fields=(
            DatasetFieldContract(
                name="change_pct",
                value_type="decimal",
                unit="percent",
                nullable=True,
                zero_allowed=True,
                source_contracts=(source_contract,),
            ),
        ),
    )


def _quote(
    *, raw_value: str, source_field: str = "pct", origin: str = "vendor_reported"
) -> QuoteSnapshot:
    return QuoteSnapshot(
        asset_code="000001.SZ",
        snapshot_at=SNAPSHOT_AT,
        fetched_at=SNAPSHOT_AT,
        current_price=10.0,
        source="vendor-main",
        change_pct_candidate=QuoteChangePctCandidate(
            raw_value=raw_value,
            source_field=source_field,
            origin=origin,
            provider_source="vendor-main",
        ),
    )


def test_quote_change_pct_uses_only_exact_source_contract_and_preserves_zero() -> None:
    source_contract = _source_contract()
    normalized = normalize_quote_snapshot_change_pct(
        _quote(raw_value="0"), _contract(source_contract)
    )

    assert normalized.change_pct == 0.0
    assert normalized.change_pct_candidate is None
    assert normalized.change_pct_evidence is not None
    assert normalized.change_pct_evidence.source_contract_hash == source_contract.content_hash
    assert normalized.change_pct_evidence.observed_at == SNAPSHOT_AT
    assert normalized.change_pct_evidence.source_value == "0"
    assert normalized.change_pct_evidence.dataset_contract_key == "equity.quote.snapshot"
    assert normalized.contract_version == "2.0"
    assert normalized.schema_version == "2.0"


def test_quote_change_pct_without_matching_contract_stays_null() -> None:
    source_contract = _source_contract()
    wrong_field = normalize_quote_snapshot_change_pct(
        _quote(raw_value="125", source_field="other_pct"), _contract(source_contract)
    )
    derived = normalize_quote_snapshot_change_pct(
        _quote(raw_value="125", origin="derived"), _contract(source_contract)
    )
    mismatched_source = normalize_quote_snapshot_change_pct(
        replace(_quote(raw_value="125"), extra={"actual_source": "other-provider"}),
        _contract(source_contract),
    )
    malformed_source = normalize_quote_snapshot_change_pct(
        replace(_quote(raw_value="125"), extra={"actual_source": 7}),
        _contract(source_contract),
    )
    absent_contract = normalize_quote_snapshot_change_pct(_quote(raw_value="125"), None)

    assert wrong_field.change_pct is None
    assert wrong_field.change_pct_evidence is None
    assert derived.change_pct is None
    assert derived.change_pct_evidence is None
    assert mismatched_source.change_pct is None
    assert mismatched_source.change_pct_evidence is None
    assert malformed_source.change_pct is None
    assert malformed_source.change_pct_evidence is None
    assert absent_contract.change_pct is None
    assert absent_contract.change_pct_evidence is None
    assert wrong_field.contract_version == "2.0"
    assert wrong_field.schema_version == "2.0"


def test_quote_metric_identity_changes_with_contract_content() -> None:
    first_contract = _source_contract(action_basis="basis-a")
    second_contract = _source_contract(action_basis="basis-b")

    first = normalize_quote_snapshot_change_pct(_quote(raw_value="125"), _contract(first_contract))
    second = normalize_quote_snapshot_change_pct(
        _quote(raw_value="125"),
        _contract(second_contract, contract_version="3.0", schema_version="3.0"),
    )

    assert first.change_pct == second.change_pct == 1.25
    assert first.change_pct_evidence is not None
    assert second.change_pct_evidence is not None
    assert (
        first.change_pct_evidence.source_contract_hash
        != second.change_pct_evidence.source_contract_hash
    )
    assert first.change_pct_evidence.dataset_contract_version == "2.0"
    assert second.change_pct_evidence.dataset_contract_version == "3.0"


def test_quote_change_pct_rejects_values_beyond_sqlite_decimal_precision() -> None:
    """Keep exact ORM round-trips inside SQLite's conservative precision bound."""

    source_contract = replace(
        _source_contract(),
        source_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
    )
    maximum_supported = normalize_quote_snapshot_change_pct(
        _quote(raw_value="123456789012.345"), _contract(source_contract)
    )
    beyond_supported = normalize_quote_snapshot_change_pct(
        _quote(raw_value="1234567890123.456"), _contract(source_contract)
    )

    assert maximum_supported.change_pct == Decimal("123456789012.345")
    assert maximum_supported.change_pct_evidence is not None
    assert beyond_supported.change_pct is None
    assert beyond_supported.change_pct_evidence is None


def test_quote_change_pct_rejects_values_that_cannot_roundtrip_storage_precision() -> None:
    hundredth_percent_contract = QuoteMetricSourceContract(
        provider_source="vendor-main",
        source_field="pct",
        origin="vendor_reported",
        source_unit="hundredth_percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=100,
        reference_session="source_quote_observation",
        action_basis="vendor_basis_unverified",
    )
    exact = normalize_quote_snapshot_change_pct(
        _quote(raw_value="123.4567891234"),
        _contract(hundredth_percent_contract),
    )
    over_precision = normalize_quote_snapshot_change_pct(
        _quote(raw_value="123.45678912345"),
        _contract(hundredth_percent_contract),
    )
    outside_decimal_column = normalize_quote_snapshot_change_pct(
        _quote(raw_value="1e28"),
        _contract(hundredth_percent_contract),
    )

    assert exact.change_pct == Decimal("1.234567891234")
    assert exact.change_pct_evidence is not None
    assert exact.change_pct_evidence.source_value == "123.4567891234"
    assert over_precision.change_pct is None
    assert over_precision.change_pct_evidence is None
    assert outside_decimal_column.change_pct is None
    assert outside_decimal_column.change_pct_evidence is None


def test_sync_quote_application_records_active_version_without_metric_activation() -> None:
    """The sync application uses catalog versions while missing source rules stay null."""

    class _ContractRepository:
        def __init__(self, contract: DatasetContract | None) -> None:
            self.contract = contract

        def get_active_for_execution(self, dataset_key: str) -> DatasetContract | None:
            assert dataset_key == "equity.quote.snapshot"
            return self.contract

    quote = _quote(raw_value="0")
    use_case = object.__new__(SyncQuoteUseCase)
    use_case._dataset_contracts = _ContractRepository(
        _contract(
            QuoteMetricSourceContract(
                provider_source="other-provider",
                source_field="different_field",
                origin="vendor_reported",
                source_unit="percent",
                canonical_unit="percent",
                scale_numerator=1,
                scale_denominator=1,
                reference_session="source_quote_observation",
                action_basis="test_contract_basis",
            )
        )
    )

    normalized = use_case._normalize_quote_metrics([quote])[0]

    assert normalized.change_pct is None
    assert normalized.change_pct_evidence is None
    assert normalized.contract_version == "2.0"
    assert normalized.schema_version == "2.0"


@pytest.mark.parametrize(
    ("contract_version", "schema_version"),
    [("1.0", "1.0"), ("2.0", "2.0")],
)
def test_quote_snapshot_mapper_round_trips_nullable_fields_and_metric_evidence(
    contract_version: str,
    schema_version: str,
) -> None:
    """Preserve nullable quote values and source-bound evidence across ORM mapping."""

    quote = normalize_quote_snapshot_change_pct(
        _quote(raw_value="125"),
        _contract(
            _source_contract(),
            contract_version=contract_version,
            schema_version=schema_version,
        ),
    )
    quote = replace(
        quote,
        open=9.5,
        volume=123.0,
        extra={
            "note": "fixture",
            "source_record_id": "provider-row-42",
            "raw_payload_hash": "a" * 64,
        },
    )

    row = quote_snapshots_to_models([quote])[0]
    row.current_price = Decimal("10.0000")
    row.open = Decimal("9.5000")
    row.volume = Decimal("123.00")
    restored = quote_snapshot_from_model(row)

    assert row.source_record_id == "provider-row-42"
    assert row.raw_payload_hash == "a" * 64
    assert row.change_pct == Decimal("1.25")
    assert row.contract_version == contract_version
    assert row.schema_version == schema_version
    assert restored.asset_code == quote.asset_code
    assert restored.snapshot_at == quote.snapshot_at
    assert restored.fetched_at == quote.fetched_at
    assert restored.current_price == 10.0
    assert (
        restored.open,
        restored.high,
        restored.low,
        restored.prev_close,
        restored.volume,
        restored.amount,
        restored.bid,
        restored.ask,
    ) == (9.5, None, None, None, 123.0, None, None, None)
    assert restored.change_pct == Decimal("1.25")
    assert restored.change_pct_evidence == quote.change_pct_evidence
    assert restored.contract_version == contract_version
    assert restored.schema_version == schema_version
    assert restored.extra["note"] == "fixture"
    assert restored.extra["source_record_id"] == "provider-row-42"
    assert restored.extra["raw_payload_hash"] == "a" * 64


def test_quote_snapshot_mapper_round_trips_null_metric_and_nullable_fields() -> None:
    """Keep absent metric evidence and nullable measurements absent on both sides."""

    row = quote_snapshots_to_models([_quote(raw_value="125")])[0]
    restored = quote_snapshot_from_model(row)

    assert row.change_pct is None
    assert restored.change_pct is None
    assert restored.change_pct_evidence is None
    assert (
        restored.open,
        restored.high,
        restored.low,
        restored.prev_close,
        restored.volume,
        restored.amount,
        restored.bid,
        restored.ask,
    ) == (None, None, None, None, None, None, None, None)


def test_quote_snapshot_mapper_rejects_non_finite_required_current_price() -> None:
    """Reject a non-finite required ORM price before creating a domain quote."""

    row = quote_snapshots_to_models([_quote(raw_value="125")])[0]
    row.current_price = Decimal("NaN")

    with pytest.raises(ValueError, match="QuoteSnapshot current_price must be a finite number"):
        quote_snapshot_from_model(row)


@pytest.mark.parametrize("invalid_value", [Decimal("NaN"), Decimal("Infinity")])
def test_quote_snapshot_mapper_rejects_invalid_nullable_numeric_values(
    invalid_value: Decimal,
) -> None:
    """Fail closed instead of defaulting malformed or non-finite stored numbers."""

    row = quote_snapshots_to_models([_quote(raw_value="125")])[0]
    row.open = invalid_value

    with pytest.raises(ValueError, match="QuoteSnapshot open must be a finite number"):
        quote_snapshot_from_model(row)


def test_quote_snapshot_mapper_rejects_non_mapping_extra() -> None:
    """Reject malformed persisted extra instead of silently replacing it with an empty map."""

    row = quote_snapshots_to_models([_quote(raw_value="125")])[0]
    row.extra = ["malformed", "json"]

    with pytest.raises(ValueError, match="QuoteSnapshotModel.extra must be a mapping"):
        quote_snapshot_from_model(row)


@pytest.mark.django_db
def test_quote_snapshot_repository_returns_latest_source_observation_per_asset() -> None:
    """Map the newest source observation for each requested asset from persisted rows."""

    older_at = SNAPSHOT_AT
    other_asset_at = SNAPSHOT_AT + timedelta(minutes=1)
    latest_at = SNAPSHOT_AT + timedelta(minutes=2)
    dataset_key = _contract(_source_contract()).key
    quotes = [
        replace(
            _quote(raw_value="125"),
            asset_code="000001.SZ",
            snapshot_at=older_at,
            fetched_at=latest_at + timedelta(minutes=1),
            current_price=10.0,
            high=10.5,
            volume=200.0,
            contract_version=dataset_key.contract_version,
            schema_version=dataset_key.schema_version,
        ),
        replace(
            _quote(raw_value="125"),
            asset_code="000001.SZ",
            snapshot_at=latest_at,
            fetched_at=latest_at,
            current_price=10.25,
            high=11.0,
            volume=None,
            amount=None,
            bid=None,
            ask=None,
            contract_version=dataset_key.contract_version,
            schema_version=dataset_key.schema_version,
        ),
        replace(
            _quote(raw_value="125"),
            asset_code="600000.SH",
            snapshot_at=other_asset_at,
            fetched_at=other_asset_at,
            current_price=22.5,
            open=22.0,
            volume=500.0,
            contract_version=dataset_key.contract_version,
            schema_version=dataset_key.schema_version,
        ),
    ]
    repository = QuoteSnapshotRepository()

    assert repository.bulk_upsert(quotes) == 3
    latest_quotes = repository.list_latest_for_asset_codes(("600000.SH", "000001.SZ"))

    assert len(latest_quotes) == 2
    assert {quote.asset_code for quote in latest_quotes} == {"000001.SZ", "600000.SH"}
    latest_by_asset = {quote.asset_code: quote for quote in latest_quotes}
    latest = latest_by_asset["000001.SZ"]
    assert latest.snapshot_at == latest_at
    assert latest.current_price == 10.25
    assert (latest.open, latest.high, latest.volume, latest.amount, latest.bid, latest.ask) == (
        None,
        11.0,
        None,
        None,
        None,
        None,
    )
    assert latest.change_pct is None
    assert latest.change_pct_evidence is None
    assert (
        latest.contract_version,
        latest.schema_version,
    ) == (dataset_key.contract_version, dataset_key.schema_version)

    other_asset = latest_by_asset["600000.SH"]
    assert other_asset.snapshot_at == other_asset_at
    assert other_asset.current_price == 22.5
    assert (other_asset.open, other_asset.high, other_asset.volume, other_asset.ask) == (
        22.0,
        None,
        500.0,
        None,
    )
    assert other_asset.change_pct is None
    assert other_asset.change_pct_evidence is None
    assert (
        other_asset.contract_version,
        other_asset.schema_version,
    ) == (dataset_key.contract_version, dataset_key.schema_version)
