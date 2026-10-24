from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

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
