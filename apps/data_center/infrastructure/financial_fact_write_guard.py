"""Atomic financial-fact writes and source-witness validation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import TypeAlias

from django.db import IntegrityError, connection, transaction
from django.db.models import Q

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.financial_source_evidence import (
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)
from apps.data_center.infrastructure.financial_decision_evidence_codec import (
    encode_financial_decision_evidence,
)
from apps.data_center.infrastructure.models import FinancialFactModel
from apps.data_center.infrastructure.publication_fact_write_lock import publication_fact_write_lock
from apps.data_center.infrastructure.publication_models import PublicationMemberModel
from core.exceptions import DataValidationError

FinancialFactNaturalKey: TypeAlias = tuple[str, date, str, str, str]
FinancialSourceTimeEvidenceVerifier: TypeAlias = Callable[[FinancialFactDecisionEvidence], bool]
_VERIFIED_TRANSPORT_EXTRA_KEYS = frozenset(
    {
        "financial_response_capture_id",
        "raw_payload_scope",
        "response_scope_basis",
        "financial_source_time_capture_id",
        "financial_source_time_body_sha256",
        "financial_source_time_row_sha256",
        "financial_source_time_match_contract_id",
        "financial_source_time_match_contract_version",
        "financial_source_time_match_contract_sha256",
        "financial_source_time_matched_row_count",
    }
)


class FinancialFactProvenanceConflictError(DataValidationError):
    """Raised when a fact update would leave a stale source witness attached."""

    default_message = "Financial fact source provenance conflicts with the update"
    default_code = "FINANCIAL_FACT_PROVENANCE_CONFLICT"


def bulk_upsert_financial_facts(
    facts: list[FinancialFact],
    *,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None = None,
) -> int:
    """Return actual inserts/updates, preserving unchanged rows and source proof."""

    if not facts:
        return 0
    _reject_duplicate_natural_keys(facts)
    for fact in facts:
        _validate_fact_decision_evidence(fact)
        decision = fact.decision_evidence
        if (
            decision is None
            or decision.source_time_witness is None
            or source_time_evidence_verifier is None
            or not source_time_evidence_verifier(decision)
        ):
            raise FinancialFactProvenanceConflictError(
                "financial source-time witness must be independently verified before write"
            )
    with transaction.atomic(), publication_fact_write_lock(FinancialFactModel):
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
        successors: list[FinancialFactModel] = []
        pinned = set(
            PublicationMemberModel._default_manager.filter(
                fact_table=FinancialFactModel._meta.db_table,
                fact_pk__in=[str(row.pk) for row in locked_before.values() if row is not None],
            ).values_list("fact_pk", flat=True)
        )
        for fact in facts:
            if locked_before[_financial_natural_key(fact)] is None:
                continue
            row = locked_after[_financial_natural_key(fact)]
            if row is None:
                raise FinancialFactProvenanceConflictError(
                    "Financial fact row disappeared during upsert"
                )
            if _update_existing_row(fact, row):
                if str(row.pk) in pinned:
                    row.pk = None
                    row.revision_number += 1
                    successors.append(row)
                    continue
                if fact.source_evidence is None:
                    normalized_updates.append(row)
                else:
                    source_updates.append(row)
        updated_count = 0
        if successors:
            inserted_count += len(
                FinancialFactModel._default_manager.bulk_create(successors, batch_size=500)
            )
        if normalized_updates:
            updated_count += FinancialFactModel._default_manager.bulk_update(
                normalized_updates,
                fields=[
                    "value",
                    "unit",
                    "report_date",
                    "available_at",
                    "extra",
                    "decision_evidence",
                ],
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
                    "decision_evidence",
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
                "-revision_number",
                "-pk",
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


def _validate_fact_decision_evidence(fact: FinancialFact) -> None:
    """Require an internally consistent source/artifact binding for every canonical write."""

    decision = fact.decision_evidence
    if decision is None:
        raise FinancialFactProvenanceConflictError(
            "financial decision evidence is required for canonical writes"
        )
    source = fact.source_evidence
    artifact = decision.artifact_reference.evidence
    if source is None or not source.is_complete:
        raise FinancialFactProvenanceConflictError(
            "financial decision evidence requires complete source evidence"
        )
    if source.raw_payload_hash != artifact.body_sha256:
        raise FinancialFactProvenanceConflictError(
            "financial decision evidence body hash differs from source evidence"
        )
    if source.source_record_id != decision.native_row_id:
        raise FinancialFactProvenanceConflictError(
            "financial decision evidence row identity differs from source evidence"
        )
    if (
        decision.native_asset_code != fact.asset_code
        or decision.native_period_end != fact.period_end
    ):
        raise FinancialFactProvenanceConflictError(
            "financial decision evidence dimensions differ from the fact"
        )
    witness = decision.source_time_witness
    if witness is None:
        raise FinancialFactProvenanceConflictError(
            "financial source-time artifact evidence is required for canonical writes"
        )
    if (
        witness.announced_at != source.announced_at
        or witness.available_at != fact.available_at
        or witness.native_asset_code != fact.asset_code
        or witness.native_period_end != fact.period_end
        or witness.financial_native_row_id != decision.native_row_id
    ):
        raise FinancialFactProvenanceConflictError(
            "financial source-time witness differs from the fact"
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


def _decision_evidence_payload(fact: FinancialFact) -> dict[str, object]:
    """Return the strict persisted projection for one fact."""

    return encode_financial_decision_evidence(fact.decision_evidence)


def _decision_evidence_matches(fact: FinancialFact, row: FinancialFactModel) -> bool:
    """Compare the exact versioned decision-evidence projection."""

    stored: object = getattr(row, "decision_evidence", None)
    return (stored if stored is not None else {}) == _decision_evidence_payload(fact)


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

    stored_decision: object = getattr(row, "decision_evidence", None)
    requested_decision = _decision_evidence_payload(fact)
    if stored_decision not in (None, {}) and not requested_decision:
        raise FinancialFactProvenanceConflictError(
            "financial decision evidence cannot be removed from an existing row"
        )
    if (
        stored_decision not in (None, {})
        and stored_decision != requested_decision
        and fact.source_evidence is not None
        and fact.source_evidence.raw_payload_hash == row.raw_payload_hash
    ):
        raise FinancialFactProvenanceConflictError(
            "financial decision evidence cannot change for the same raw payload"
        )
    if not _row_has_source_evidence(row):
        return
    normalized_same = _normalized_fields_match(fact, row)
    evidence = fact.source_evidence
    if not normalized_same:
        if evidence is None or not evidence.is_complete:
            raise FinancialFactProvenanceConflictError(
                "stale financial source evidence requires complete replacement evidence"
            )
        if (
            evidence.raw_payload_hash == row.raw_payload_hash
            and not _is_transport_metadata_upgrade(fact, row)
        ):
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
    if fact.decision_evidence is not None and not _decision_evidence_matches(fact, row):
        raise FinancialFactProvenanceConflictError(
            "concurrent financial decision evidence differs from the requested witness"
        )


def _is_transport_metadata_upgrade(fact: FinancialFact, row: FinancialFactModel) -> bool:
    """Allow only verified transport keys to augment an otherwise identical row."""

    if fact.decision_evidence is None:
        return False
    stored_extra_raw: object = getattr(row, "extra", None)
    if not isinstance(stored_extra_raw, dict):
        return False
    if any(fact.extra.get(key) != value for key, value in stored_extra_raw.items()):
        return False
    added_keys = frozenset(fact.extra) - frozenset(stored_extra_raw)
    if not added_keys or not added_keys.issubset(_VERIFIED_TRANSPORT_EXTRA_KEYS):
        return False
    decision = fact.decision_evidence
    artifact = decision.artifact_reference
    source_time = decision.source_time_witness
    if source_time is None:
        return False
    source_time_artifact = source_time.artifact_reference
    expected = {
        "financial_response_capture_id": str(artifact.capture_id),
        "raw_payload_scope": artifact.evidence.body_scope.value,
        "response_scope_basis": artifact.evidence.response_scope_basis.value,
        "financial_source_time_capture_id": str(source_time_artifact.capture_id),
        "financial_source_time_body_sha256": source_time_artifact.body_sha256,
        "financial_source_time_row_sha256": source_time.row_projection_sha256,
        "financial_source_time_match_contract_id": source_time.governed_match_contract_id,
        "financial_source_time_match_contract_version": (
            source_time.governed_match_contract_version
        ),
        "financial_source_time_match_contract_sha256": source_time.governed_match_contract_sha256,
        "financial_source_time_matched_row_count": source_time.matched_row_count,
    }
    return all(fact.extra.get(key) == value for key, value in expected.items())


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
        decision_evidence=_decision_evidence_payload(fact),
        announced_at=announced_at,
        source_record_id=source_record_id,
        raw_payload_hash=raw_payload_hash,
    )


def _update_existing_row(fact: FinancialFact, row: FinancialFactModel) -> bool:
    """Apply one prevalidated in-memory update and report whether it changed."""

    if (
        _normalized_fields_match(fact, row)
        and (fact.source_evidence is None or _source_fields_match(fact, row))
        and _decision_evidence_matches(fact, row)
    ):
        return False
    row.value = fact.value
    row.unit = fact.unit
    row.report_date = fact.report_date
    row.available_at = fact.available_at
    row.extra = fact.extra
    row.decision_evidence = _decision_evidence_payload(fact)
    if fact.source_evidence is not None:
        announced_at, source_record_id, raw_payload_hash = _source_fields(fact)
        row.announced_at = announced_at
        row.source_record_id = source_record_id
        row.raw_payload_hash = raw_payload_hash
    return True


__all__ = [
    "FinancialFactProvenanceConflictError",
    "FinancialSourceTimeEvidenceVerifier",
    "bulk_upsert_financial_facts",
    "source_evidence_from_model",
]
