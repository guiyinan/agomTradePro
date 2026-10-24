"""Catalog-bound quote metric normalization at the provider application boundary."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    QuoteMetricSourceContract,
)
from apps.data_center.domain.entities import QuoteChangePctEvidence, QuoteSnapshot
from apps.data_center.domain.quote_change_pct import quote_change_pct_storage_value
from shared.numeric import safe_float


def _quote_metric_field_contract(
    contract: DatasetContract,
) -> DatasetFieldContract | None:
    """Select the unique canonical quote metric schema field, if present."""

    if contract.key.value != "equity.quote.snapshot":
        return None
    fields = [field for field in contract.fields if field.name == "change_pct"]
    return fields[0] if len(fields) == 1 else None


def _quote_metric_source_contract(
    quote: QuoteSnapshot,
    field_contract: DatasetFieldContract | None,
) -> QuoteMetricSourceContract | None:
    """Select one exact quote source-field rule or leave the metric unknown."""

    if field_contract is None:
        return None
    candidate = quote.change_pct_candidate
    if candidate is None or candidate.origin != "vendor_reported":
        return None
    if "actual_source" in quote.extra:
        actual_source = quote.extra.get("actual_source")
        if not isinstance(actual_source, str) or not actual_source.strip():
            return None
    else:
        actual_source = quote.source
    if candidate.provider_source != actual_source:
        return None
    matches = [
        source_contract
        for source_contract in field_contract.source_contracts
        if source_contract.provider_source == candidate.provider_source
        and source_contract.source_field == candidate.source_field
        and source_contract.origin == candidate.origin
    ]
    return matches[0] if len(matches) == 1 else None


def normalize_quote_snapshot_change_pct(
    quote: QuoteSnapshot,
    contract: DatasetContract | None,
) -> QuoteSnapshot:
    """Attach a vendor metric only when one exact active source contract qualifies it.

    Missing contracts, derived values, malformed numbers, and values that cannot
    round-trip through the canonical Decimal column remain explicitly unknown.
    No previous close or price arithmetic is used to manufacture a percentage.
    """

    if contract is None or contract.key.value != "equity.quote.snapshot":
        return replace(
            quote,
            change_pct=None,
            change_pct_candidate=None,
            change_pct_evidence=None,
            contract_version=None,
            schema_version=None,
        )
    field_contract = _quote_metric_field_contract(contract)
    source_contract = _quote_metric_source_contract(quote, field_contract)
    candidate = quote.change_pct_candidate
    if source_contract is None or candidate is None:
        return replace(
            quote,
            change_pct=None,
            change_pct_candidate=None,
            change_pct_evidence=None,
            contract_version=contract.key.contract_version,
            schema_version=contract.key.schema_version,
        )
    if (
        field_contract is None
        or field_contract.value_type != "decimal"
        or field_contract.unit != "percent"
        or not field_contract.nullable
    ):
        return replace(
            quote,
            change_pct=None,
            change_pct_candidate=None,
            change_pct_evidence=None,
            contract_version=contract.key.contract_version,
            schema_version=contract.key.schema_version,
        )
    if source_contract.canonical_unit != "percent":
        return replace(
            quote,
            change_pct=None,
            change_pct_candidate=None,
            change_pct_evidence=None,
            contract_version=contract.key.contract_version,
            schema_version=contract.key.schema_version,
        )
    if safe_float(candidate.raw_value, default=None) is None:
        return replace(
            quote,
            change_pct=None,
            change_pct_candidate=None,
            change_pct_evidence=None,
            contract_version=contract.key.contract_version,
            schema_version=contract.key.schema_version,
        )
    try:
        raw_value = Decimal(candidate.raw_value)
        scaled_fraction = Fraction(raw_value) * Fraction(
            source_contract.scale_numerator,
            source_contract.scale_denominator,
        )
        stored_value = quote_change_pct_storage_value(scaled_fraction)
    except (InvalidOperation, ValueError, OverflowError, ZeroDivisionError):
        return replace(
            quote,
            change_pct=None,
            change_pct_candidate=None,
            change_pct_evidence=None,
            contract_version=contract.key.contract_version,
            schema_version=contract.key.schema_version,
        )
    if stored_value is None:
        return replace(
            quote,
            change_pct=None,
            change_pct_candidate=None,
            change_pct_evidence=None,
            contract_version=contract.key.contract_version,
            schema_version=contract.key.schema_version,
        )
    if (
        (not field_contract.zero_allowed and stored_value == 0)
        or (
            field_contract.minimum is not None
            and stored_value < Decimal(str(field_contract.minimum))
        )
        or (
            field_contract.maximum is not None
            and stored_value > Decimal(str(field_contract.maximum))
        )
    ):
        return replace(
            quote,
            change_pct=None,
            change_pct_candidate=None,
            change_pct_evidence=None,
            contract_version=contract.key.contract_version,
            schema_version=contract.key.schema_version,
        )
    evidence = QuoteChangePctEvidence(
        metric_value=stored_value,
        source_value=candidate.raw_value,
        dataset_contract_key=contract.key.value,
        dataset_contract_version=contract.key.contract_version,
        dataset_schema_version=contract.key.schema_version,
        source_contract=source_contract,
        source_contract_hash=source_contract.content_hash,
        observed_at=quote.snapshot_at,
        quote_source=quote.source,
    )
    return replace(
        quote,
        change_pct=stored_value,
        change_pct_candidate=None,
        change_pct_evidence=evidence,
        contract_version=contract.key.contract_version,
        schema_version=contract.key.schema_version,
    )


__all__ = ["normalize_quote_snapshot_change_pct"]
