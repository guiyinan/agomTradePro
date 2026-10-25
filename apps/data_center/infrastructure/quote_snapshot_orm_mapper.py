"""Map quote snapshots between the domain and their Django ORM rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any, cast

from apps.data_center.domain.entities import QuoteChangePctEvidence, QuoteSnapshot
from apps.data_center.domain.quote_change_pct import quote_change_pct_storage_value
from shared.numeric import safe_float

from .quote_snapshot_models import QuoteSnapshotModel


def _quote_transport_identity(extra: Mapping[str, object]) -> tuple[str, str]:
    """Return the bounded transport identity values stored in separate columns."""

    source_record_id = extra.get("source_record_id")
    if (
        not isinstance(source_record_id, str)
        or not source_record_id.strip()
        or len(source_record_id) > 200
    ):
        source_record_id = ""
    raw_payload_hash = extra.get("raw_payload_hash")
    if (
        not isinstance(raw_payload_hash, str)
        or len(raw_payload_hash) != 64
        or any(character not in "0123456789abcdef" for character in raw_payload_hash)
    ):
        raw_payload_hash = ""
    return source_record_id, raw_payload_hash


def _required_float(value: object, field_name: str) -> float:
    """Convert a required ORM numeric field, failing closed for invalid values."""

    number = safe_float(value)
    if number is None:
        raise ValueError(f"QuoteSnapshot {field_name} must be a finite number")
    return number


def _optional_float(value: object, field_name: str) -> float | None:
    """Convert a nullable ORM numeric field without hiding invalid stored values."""

    if value is None:
        return None
    number = safe_float(value)
    if number is None:
        raise ValueError(f"QuoteSnapshot {field_name} must be a finite number")
    return number


def quote_snapshot_from_model(model: QuoteSnapshotModel) -> QuoteSnapshot:
    """Build one domain quote while retaining its stored metric evidence."""

    if not isinstance(model.extra, Mapping):
        raise ValueError("QuoteSnapshotModel.extra must be a mapping")
    extra = cast(Mapping[str, object], model.extra)
    persisted_extra = cast(dict[str, Any], dict(extra))
    if model.source_record_id:
        persisted_extra["source_record_id"] = model.source_record_id
    if model.raw_payload_hash:
        persisted_extra["raw_payload_hash"] = model.raw_payload_hash
    change_pct = model.change_pct
    metric_evidence_payload = extra.get("change_pct_source_contract")
    metric_evidence = (
        QuoteChangePctEvidence.from_payload(metric_evidence_payload)
        if change_pct is not None
        else None
    )
    if change_pct is None and metric_evidence_payload is not None:
        raise ValueError("Quote metric evidence exists without a canonical change_pct")
    return QuoteSnapshot(
        asset_code=model.asset_code,
        snapshot_at=model.snapshot_at,
        fetched_at=model.fetched_at,
        current_price=_required_float(model.current_price, "current_price"),
        open=_optional_float(model.open, "open"),
        high=_optional_float(model.high, "high"),
        low=_optional_float(model.low, "low"),
        prev_close=_optional_float(model.prev_close, "prev_close"),
        volume=_optional_float(model.volume, "volume"),
        amount=_optional_float(model.amount, "amount"),
        bid=_optional_float(model.bid, "bid"),
        ask=_optional_float(model.ask, "ask"),
        change_pct=change_pct,
        change_pct_evidence=metric_evidence,
        contract_version=model.contract_version,
        schema_version=model.schema_version,
        source=model.source,
        extra=persisted_extra,
        ingested_run_id=str(model.ingested_run_id) if model.ingested_run_id else "",
    )


def quote_snapshots_to_models(quotes: Sequence[QuoteSnapshot]) -> list[QuoteSnapshotModel]:
    """Map a quote batch to ORM rows using the existing exact storage contract."""

    for quote in quotes:
        if quote.change_pct is None:
            continue
        storage_value = quote_change_pct_storage_value(Fraction(quote.change_pct))
        if storage_value != quote.change_pct:
            raise ValueError(
                "quote change_pct is not exactly representable by the canonical storage field"
            )

    rows: list[QuoteSnapshotModel] = []
    for quote in quotes:
        extra = dict(quote.extra)
        source_record_id, raw_payload_hash = _quote_transport_identity(extra)
        if quote.change_pct_evidence is None:
            extra.pop("change_pct_source_contract", None)
        else:
            extra["change_pct_source_contract"] = quote.change_pct_evidence.to_dict()
        row = QuoteSnapshotModel(
            asset_code=quote.asset_code,
            snapshot_at=quote.snapshot_at,
            source=quote.source,
            current_price=quote.current_price,
            fetched_at=quote.fetched_at,
            open=quote.open,
            high=quote.high,
            low=quote.low,
            prev_close=quote.prev_close,
            volume=quote.volume,
            amount=quote.amount,
            bid=quote.bid,
            ask=quote.ask,
            change_pct=quote.change_pct,
            source_record_id=source_record_id,
            raw_payload_hash=raw_payload_hash,
            extra=extra,
            ingested_run_id=quote.ingested_run_id or None,
        )
        if quote.contract_version is not None and quote.schema_version is not None:
            row.contract_version = quote.contract_version
            row.schema_version = quote.schema_version
        rows.append(row)
    return rows


__all__ = ["quote_snapshot_from_model", "quote_snapshots_to_models"]
