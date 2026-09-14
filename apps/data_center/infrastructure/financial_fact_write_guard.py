"""Atomic financial-fact writes and source-witness validation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import TypeAlias

from django.db import IntegrityError, connection, transaction
from django.db.models import Q

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.financial_source_evidence import FinancialFactSourceEvidence
from apps.data_center.infrastructure.models import FinancialFactModel
from core.exceptions import DataValidationError

FinancialFactNaturalKey: TypeAlias = tuple[str, date, str, str, str]


class FinancialFactProvenanceConflictError(DataValidationError):
    """Raised when a fact update would leave a stale source witness attached."""

    default_message = "Financial fact source provenance conflicts with the update"
    default_code = "FINANCIAL_FACT_PROVENANCE_CONFLICT"


def bulk_upsert_financial_facts(facts: list[FinancialFact]) -> int:
    """Return actual inserts/updates, preserving unchanged rows and source proof."""

    if not facts:
        return 0
    _reject_duplicate_natural_keys(facts)
    with transaction.atomic():
        locked_before = _lock_rows_by_natural_key(facts)
        for fact in facts:
            row = locked_before[_financial_natural_key(fact)]
            if row is not None:
                _validate_existing_row_update(fact, row)

        missing = [fact for fact in facts if locked_before[_financial_natural_key(fact)] is None]
        inserted_count = _insert_missing_facts(missing)

        locked_after = dict(locked_before)
        if missing:
            locked_after.update(_lock_rows_by_natural_key(missing))
        for fact in missing:
            row = locked_after[_financial_natural_key(fact)]
            if row is None:
                raise FinancialFactProvenanceConflictError(
                    "Financial fact row disappeared during upsert"
                )
            _validate_missing_row_race(fact, row)

        normalized_updates: list[FinancialFactModel] = []
        source_updates: list[FinancialFactModel] = []
        for fact in facts:
            if locked_before[_financial_natural_key(fact)] is None:
                continue
            row = locked_after[_financial_natural_key(fact)]
            if row is None:
                raise FinancialFactProvenanceConflictError(
                    "Financial fact row disappeared during upsert"
                )
            if _update_existing_row(fact, row):
                if fact.source_evidence is None:
                    normalized_updates.append(row)
                else:
                    source_updates.append(row)
        updated_count = 0
        if normalized_updates:
            updated_count += FinancialFactModel._default_manager.bulk_update(
                normalized_updates,
                fields=["value", "unit", "report_date", "available_at", "extra"],
                batch_size=1_000,
            )
        if source_updates:
            updated_count += FinancialFactModel._default_manager.bulk_update(
                source_updates,
                fields=[
                    "value",
                    "unit",
                    "report_date",
                    "available_at",
                    "extra",
                    "announced_at",
                    "source_record_id",
                    "raw_payload_hash",
                ],
                batch_size=1_000,
            )
        if updated_count != len(normalized_updates) + len(source_updates):
            raise FinancialFactProvenanceConflictError("Financial fact update lost a locked row")
    return inserted_count + updated_count


def _insert_missing_facts(facts: list[FinancialFact]) -> int:
    """Insert a batch, checking one unique-key race without counting its winner.

    A failed batch is rolled back to a savepoint before its committed natural
    keys are reread. Matching winners are retained; remaining missing rows get
    one insertion attempt. A further conflict aborts the whole outer batch.
    """

    if not facts:
        return 0
    try:
        return _insert_new_batch(facts)
    except IntegrityError:
        raced_rows = _lock_rows_by_natural_key(facts)
        winners = [fact for fact in facts if raced_rows[_financial_natural_key(fact)] is not None]
        if not winners:
            raise
        for fact in winners:
            row = raced_rows[_financial_natural_key(fact)]
            if row is not None:
                _validate_missing_row_race(fact, row)
        remaining = [fact for fact in facts if raced_rows[_financial_natural_key(fact)] is None]
        return _insert_new_batch(remaining)


def _insert_new_batch(facts: list[FinancialFact]) -> int:
    """Count successful new inserts; never discard conflicts or overwrite winners."""

    if not facts:
        return 0
    ordered_facts = sorted(facts, key=_financial_natural_key)
    with transaction.atomic():
        created = FinancialFactModel._default_manager.bulk_create(
            [_model_from_fact(fact) for fact in ordered_facts], batch_size=1_000
        )
    return len(created)


def source_evidence_from_model(
    model: FinancialFactModel,
) -> FinancialFactSourceEvidence | None:
    """Narrow the three existing ORM source fields into one Domain value."""

    announced_raw: object = getattr(model, "announced_at", None)
    source_record_raw: object = getattr(model, "source_record_id", "")
    raw_hash_raw: object = getattr(model, "raw_payload_hash", "")
    if announced_raw is not None and not isinstance(announced_raw, datetime):
        raise FinancialFactProvenanceConflictError(
            "Financial fact announced_at has an invalid ORM type"
        )
    if not isinstance(source_record_raw, str):
        raise FinancialFactProvenanceConflictError(
            "Financial fact source_record_id has an invalid ORM type"
        )
    if not isinstance(raw_hash_raw, str):
        raise FinancialFactProvenanceConflictError(
            "Financial fact raw_payload_hash has an invalid ORM type"
        )
    announced_at = announced_raw if isinstance(announced_raw, datetime) else None
    source_record_id = source_record_raw or None
    raw_payload_hash = raw_hash_raw or None
    if announced_at is None and source_record_id is None and raw_payload_hash is None:
        return None
    return FinancialFactSourceEvidence(
        announced_at=announced_at,
        source_record_id=source_record_id,
        raw_payload_hash=raw_payload_hash,
    )


def _financial_natural_key(fact: FinancialFact) -> FinancialFactNaturalKey:
    """Return the model's unique natural key for one Domain fact."""

    return (
        fact.asset_code,
        fact.period_end,
        fact.period_type.value,
        fact.metric_code,
        fact.source,
    )


def _lock_rows_by_natural_key(
    facts: Sequence[FinancialFact],
) -> dict[FinancialFactNaturalKey, FinancialFactModel | None]:
    """Lock matching rows in sorted, backend-sized natural-key chunks.

    The exact-key disjunction keeps one query per chunk while ``order_by``
    makes row-lock acquisition deterministic.  The chunk size is derived from
    the active backend's parameter budget; it is an SQL-shape limit rather
    than a business batch size.
    """

    keys = sorted({_financial_natural_key(fact) for fact in facts})
    rows: dict[FinancialFactNaturalKey, FinancialFactModel | None] = dict.fromkeys(keys)
    if not keys:
        return rows
    chunk_size = _natural_key_query_chunk_size()
    for offset in range(0, len(keys), chunk_size):
        key_chunk = keys[offset : offset + chunk_size]
        predicate = Q()
        for asset_code, period_end, period_type, metric_code, source in key_chunk:
            predicate |= Q(
                asset_code=asset_code,
                period_end=period_end,
                period_type=period_type,
                metric_code=metric_code,
                source=source,
            )
        for row in (
            FinancialFactModel._default_manager.select_for_update()
            .filter(predicate)
            .order_by(
                "asset_code",
                "period_end",
                "period_type",
                "metric_code",
                "source",
                "pk",
            )
        ):
            key = _row_natural_key(row)
            if key in rows and rows[key] is None:
                rows[key] = row
    return rows


def _natural_key_query_chunk_size() -> int:
    """Return a safe disjunction size for the active database backend."""

    max_query_params_raw: object = getattr(connection.features, "max_query_params", None)
    if max_query_params_raw is None:
        return 200
    if not isinstance(max_query_params_raw, int):
        return 200
    return max(1, max_query_params_raw // 5)


def _row_natural_key(row: FinancialFactModel) -> FinancialFactNaturalKey:
    """Return the persisted model natural key in Domain tuple order."""

    return (
        row.asset_code,
        row.period_end,
        row.period_type,
        row.metric_code,
        row.source,
    )


def _reject_duplicate_natural_keys(facts: Sequence[FinancialFact]) -> None:
    """Reject duplicate input keys before an upsert can partially proceed."""

    keys = [_financial_natural_key(fact) for fact in facts]
    if len(set(keys)) != len(keys):
        raise FinancialFactProvenanceConflictError(
            "Financial fact batch contains duplicate natural keys"
        )


def _normalized_fields_match(fact: FinancialFact, row: FinancialFactModel) -> bool:
    """Compare fields the legacy upsert is allowed to replace."""

    stored_extra: object = getattr(row, "extra", None)
    return (
        _model_decimal_storage(fact.value) == _model_decimal_storage(row.value)
        and row.unit == fact.unit
        and row.report_date == fact.report_date
        and row.available_at == fact.available_at
        and (stored_extra if stored_extra is not None else {}) == fact.extra
    )


def _model_decimal_storage(value: object) -> str:
    """Return the model field's backend-shaped decimal representation.

    The unchanged writer passes the original float through DecimalField.
    PostgreSQL numeric rounds ties away from zero; SQLite's Django read
    converter applies its own numeric-affinity precision. Neither path adds a
    business decimal-place rule or converts floats to a different text value.
    """

    value_field = FinancialFactModel._meta.get_field("value")
    prepared: object = value_field.get_db_prep_save(value, connection)
    if not isinstance(prepared, Decimal):
        prepared = value_field.to_python(prepared)
    if not isinstance(prepared, Decimal):
        raise FinancialFactProvenanceConflictError(
            "financial value cannot be normalized by its model field"
        )
    precision: object = value_field.max_digits
    scale: object = value_field.decimal_places
    if type(precision) is not int or type(scale) is not int:
        raise FinancialFactProvenanceConflictError(
            "financial decimal field precision is unavailable"
        )
    if connection.vendor == "postgresql":
        with localcontext() as context:
            context.prec = precision
            stored = prepared.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    elif connection.vendor == "sqlite":
        expression = value_field.get_col(FinancialFactModel._meta.db_table)
        low, high = connection.ops.integer_field_range("BigIntegerField")
        raw_numeric: int | float
        if low <= prepared <= high and prepared == prepared.to_integral_value():
            raw_numeric = int(prepared)
        else:
            raw_numeric = float(prepared)
        converted: object = raw_numeric
        for converter in connection.ops.get_db_converters(expression):
            converted = converter(converted, expression, connection)
        if not isinstance(converted, Decimal):
            raise FinancialFactProvenanceConflictError(
                "financial SQLite decimal converter is unavailable"
            )
        stored = converted
    else:
        raise FinancialFactProvenanceConflictError(
            "financial source guard requires a supported decimal storage backend"
        )
    return format(stored, "f")


def _source_fields(fact: FinancialFact) -> tuple[datetime | None, str, str]:
    """Return source fields in the model representation used by the writer."""

    evidence = fact.source_evidence
    if evidence is None:
        return None, "", ""
    return (
        evidence.announced_at,
        evidence.source_record_id or "",
        evidence.raw_payload_hash or "",
    )


def _row_has_source_evidence(row: FinancialFactModel) -> bool:
    """Return whether a row contains any existing source witness field."""

    return bool(
        row.announced_at is not None or bool(row.source_record_id) or bool(row.raw_payload_hash)
    )


def _source_fields_match(fact: FinancialFact, row: FinancialFactModel) -> bool:
    """Compare all source fields without applying a fallback identity."""

    announced_at, source_record_id, raw_payload_hash = _source_fields(fact)
    return (
        row.announced_at == announced_at
        and row.source_record_id == source_record_id
        and row.raw_payload_hash == raw_payload_hash
    )


def _validate_existing_row_update(fact: FinancialFact, row: FinancialFactModel) -> None:
    """Reject a value update that would retain or merge stale source proof."""

    if not _row_has_source_evidence(row):
        return
    normalized_same = _normalized_fields_match(fact, row)
    evidence = fact.source_evidence
    if not normalized_same:
        if evidence is None or not evidence.is_complete:
            raise FinancialFactProvenanceConflictError(
                "stale financial source evidence requires complete replacement evidence"
            )
        if evidence.raw_payload_hash == row.raw_payload_hash:
            raise FinancialFactProvenanceConflictError(
                "changed financial value cannot reuse the same raw payload"
            )
        return
    if evidence is not None and not evidence.is_complete and not _source_fields_match(fact, row):
        raise FinancialFactProvenanceConflictError(
            "partial financial source evidence cannot replace an existing witness"
        )


def _validate_missing_row_race(fact: FinancialFact, row: FinancialFactModel) -> None:
    """Verify an ignored conflict did not hide a concurrent source-bearing row."""

    if not _normalized_fields_match(fact, row):
        raise FinancialFactProvenanceConflictError(
            "concurrent financial fact row conflicts with the requested update"
        )
    if fact.source_evidence is not None and not _source_fields_match(fact, row):
        raise FinancialFactProvenanceConflictError(
            "concurrent financial source evidence differs from the requested witness"
        )


def _model_from_fact(fact: FinancialFact) -> FinancialFactModel:
    """Build an ORM row without fabricating absent source fields."""

    announced_at, source_record_id, raw_payload_hash = _source_fields(fact)
    return FinancialFactModel(
        asset_code=fact.asset_code,
        period_end=fact.period_end,
        period_type=fact.period_type.value,
        metric_code=fact.metric_code,
        value=fact.value,
        unit=fact.unit,
        source=fact.source,
        report_date=fact.report_date,
        available_at=fact.available_at,
        extra=fact.extra,
        announced_at=announced_at,
        source_record_id=source_record_id,
        raw_payload_hash=raw_payload_hash,
    )


def _update_existing_row(fact: FinancialFact, row: FinancialFactModel) -> bool:
    """Apply one prevalidated in-memory update and report whether it changed."""

    if _normalized_fields_match(fact, row) and (
        fact.source_evidence is None or _source_fields_match(fact, row)
    ):
        return False
    row.value = fact.value
    row.unit = fact.unit
    row.report_date = fact.report_date
    row.available_at = fact.available_at
    row.extra = fact.extra
    if fact.source_evidence is not None:
        announced_at, source_record_id, raw_payload_hash = _source_fields(fact)
        row.announced_at = announced_at
        row.source_record_id = source_record_id
        row.raw_payload_hash = raw_payload_hash
    return True


__all__ = [
    "FinancialFactProvenanceConflictError",
    "bulk_upsert_financial_facts",
    "source_evidence_from_model",
]
