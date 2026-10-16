"""Append-only repository for exact source-bound instrument snapshots."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, router, transaction
from django.utils import timezone

from apps.data_center.application.instrument_reference_snapshot import (
    InstrumentReferenceSnapshotRepositoryPort,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceMappingContent,
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
    make_instrument_reference_mapping_record,
    make_instrument_reference_snapshot_record,
    mapping_content_from_payload,
    snapshot_content_from_payload,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceOccurrence,
    InstrumentReferenceRecord,
)
from apps.data_center.domain.protocols import RawAuditRepositoryProtocol
from apps.data_center.domain.provider_response import canonical_provider_response_json
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    _bind_rows_to_occurrence,
    _parse_stock_basic_rows,
)

from .models import (
    InstrumentReferenceMappingModel,
    InstrumentReferenceSnapshotModel,
    RawAuditModel,
    RawPayloadModel,
)


class InstrumentReferenceSnapshotPersistenceError(ValueError):
    """A stable persistence or source-evidence block for instrument snapshots."""

    def __init__(self, code: str) -> None:
        """Expose one machine-readable reason to the application caller."""

        self.code = code
        super().__init__(code)


class _ExactRawPayloadReader(Protocol):
    """Read a hash-addressed payload by its exact persisted identifier."""

    @property
    def unit_of_work_key(self) -> str:
        """Identify the database alias used by exact raw-payload reads."""

    def get_by_id(self, payload_id: str) -> RawPayload | None:
        """Return the precise immutable payload row or no result."""


class _DefaultRawAuditRepository(RawAuditRepositoryProtocol, Protocol):
    """Require the existing raw audit repository's explicitly named default alias."""

    @property
    def unit_of_work_key(self) -> str:
        """Expose the database alias identity shared with this repository."""


class DjangoInstrumentReferenceSnapshotRepository(InstrumentReferenceSnapshotRepositoryPort):
    """Persist full candidate JSON and verify each actual RawAudit/RawPayload occurrence."""

    def __init__(
        self,
        raw_audit_repository: _DefaultRawAuditRepository,
        raw_payload_reader: _ExactRawPayloadReader,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Inject existing default-alias readers and an optional test clock."""

        audit_unit_of_work_key = raw_audit_repository.unit_of_work_key
        payload_unit_of_work_key = getattr(raw_payload_reader, "unit_of_work_key", None)
        if audit_unit_of_work_key != "django:default":
            raise ValueError("instrument-reference snapshot requires the default alias")
        if payload_unit_of_work_key != audit_unit_of_work_key:
            raise ValueError("instrument-reference evidence repositories must share one alias")
        if payload_unit_of_work_key != "django:default":
            raise ValueError("instrument-reference snapshot requires the default alias")
        self._raw_audit_repository = raw_audit_repository
        self._raw_payload_reader = raw_payload_reader
        self._clock = clock
        self._using = "default"
        for model in (
            RawAuditModel,
            RawPayloadModel,
            InstrumentReferenceMappingModel,
            InstrumentReferenceSnapshotModel,
        ):
            route_targets = (router.db_for_read(model), router.db_for_write(model))
            if any(alias is not None and alias != self._using for alias in route_targets):
                raise ValueError(
                    "instrument-reference facts and raw evidence must route to the default alias"
                )

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact alias used for mapping, snapshot and raw evidence reads."""

        return "django:default"

    def save_mapping(
        self,
        content: InstrumentReferenceMappingContent,
    ) -> InstrumentReferenceMappingRecord:
        """Append mapping content or return its byte-for-byte same-version receipt."""

        if not isinstance(content, InstrumentReferenceMappingContent):
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_MAPPING_INVALID"
            )
        with transaction.atomic(using=self._using):
            existing = (
                InstrumentReferenceMappingModel.objects.using(self._using)
                .filter(
                    mapping_id=content.mapping_id,
                    mapping_version=content.mapping_version,
                )
                .first()
            )
            if existing is not None:
                receipt = self._mapping_receipt(existing)
                if receipt.content != content:
                    raise InstrumentReferenceSnapshotPersistenceError(
                        "INSTRUMENT_REFERENCE_MAPPING_VERSION_IMMUTABLE"
                    ) from None
                return receipt
            now = self._now()
            receipt = make_instrument_reference_mapping_record(
                content,
                mapping_record_id=uuid4(),
                recorded_at=now,
            )
            model = InstrumentReferenceMappingModel(
                mapping_record_id=receipt.mapping_record_id,
                mapping_id=content.mapping_id,
                mapping_version=content.mapping_version,
                source_crosswalk_id=content.source_crosswalk_id,
                source_crosswalk_version=content.source_crosswalk_version,
                source_crosswalk_hash=content.source_crosswalk_hash,
                content=content.to_payload(),
                content_hash=receipt.content_hash,
                recorded_at=receipt.recorded_at,
                record_digest=receipt.record_digest,
            )
            try:
                with transaction.atomic(using=self._using):
                    model.full_clean(validate_unique=False, validate_constraints=False)
                    model.save(using=self._using, force_insert=True)
            except IntegrityError:
                winner = (
                    InstrumentReferenceMappingModel.objects.using(self._using)
                    .filter(
                        mapping_id=content.mapping_id,
                        mapping_version=content.mapping_version,
                    )
                    .first()
                )
                if winner is None:
                    raise
                persisted = self._mapping_receipt(winner)
                if persisted.content != content:
                    raise InstrumentReferenceSnapshotPersistenceError(
                        "INSTRUMENT_REFERENCE_MAPPING_VERSION_IMMUTABLE"
                    ) from None
                return persisted
            return receipt

    def save_snapshot(
        self,
        content: InstrumentReferenceSnapshotContent,
    ) -> InstrumentReferenceSnapshotRecord:
        """Validate every exact source occurrence and insert one complete sealed batch."""

        if not isinstance(content, InstrumentReferenceSnapshotContent):
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_SNAPSHOT_INVALID"
            )
        with transaction.atomic(using=self._using):
            mapping_model = (
                InstrumentReferenceMappingModel.objects.using(self._using)
                .filter(pk=content.mapping_record.mapping_record_id)
                .first()
            )
            if mapping_model is None:
                raise InstrumentReferenceSnapshotPersistenceError(
                    "INSTRUMENT_REFERENCE_MAPPING_NOT_PERSISTED"
                )
            persisted_mapping = self._mapping_receipt(mapping_model)
            if persisted_mapping != content.mapping_record:
                raise InstrumentReferenceSnapshotPersistenceError(
                    "INSTRUMENT_REFERENCE_MAPPING_RECEIPT_MISMATCH"
                )
            self._verify_raw_evidence(content)
            existing = (
                InstrumentReferenceSnapshotModel.objects.using(self._using)
                .filter(content_hash=content.content_hash)
                .first()
            )
            if existing is not None:
                receipt = self._snapshot_receipt(existing)
                if receipt.content != content:
                    raise InstrumentReferenceSnapshotPersistenceError(
                        "INSTRUMENT_REFERENCE_SNAPSHOT_CONTENT_CONFLICT"
                    ) from None
                return receipt
            now = self._now()
            if now < content.last_response_completed_at or now < persisted_mapping.recorded_at:
                raise InstrumentReferenceSnapshotPersistenceError(
                    "INSTRUMENT_REFERENCE_REPOSITORY_CLOCK_BEFORE_EVIDENCE"
                )
            receipt = make_instrument_reference_snapshot_record(
                content,
                snapshot_id=uuid4(),
                recorded_at=now,
            )
            model = InstrumentReferenceSnapshotModel(
                snapshot_id=receipt.snapshot_id,
                run_id=content.run_id,
                mapping_record=mapping_model,
                snapshot_payload=content.to_payload(),
                content_hash=receipt.content_hash,
                recorded_at=receipt.recorded_at,
                record_digest=receipt.record_digest,
                round_count=len(content.fetch_rounds),
                occurrence_count=content.occurrence_count,
                record_count=content.record_count,
            )
            try:
                with transaction.atomic(using=self._using):
                    model.full_clean(validate_unique=False, validate_constraints=False)
                    model.save(using=self._using, force_insert=True)
            except IntegrityError:
                winner = (
                    InstrumentReferenceSnapshotModel.objects.using(self._using)
                    .filter(content_hash=content.content_hash)
                    .first()
                )
                if winner is None:
                    raise
                persisted = self._snapshot_receipt(winner)
                if persisted.content != content:
                    raise InstrumentReferenceSnapshotPersistenceError(
                        "INSTRUMENT_REFERENCE_SNAPSHOT_CONTENT_CONFLICT"
                    ) from None
                return persisted
            return receipt

    def get_snapshot(self, snapshot_id: UUID) -> InstrumentReferenceSnapshotRecord | None:
        """Load one exact snapshot and recheck all seals plus external raw evidence."""

        if not isinstance(snapshot_id, UUID):
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_SNAPSHOT_ID_INVALID"
            )
        model = (
            InstrumentReferenceSnapshotModel.objects.using(self._using)
            .filter(pk=snapshot_id)
            .first()
        )
        if model is None:
            return None
        receipt = self._snapshot_receipt(model)
        self._verify_raw_evidence(receipt.content)
        return receipt

    def get_mapping(self, mapping_record_id: UUID) -> InstrumentReferenceMappingRecord | None:
        """Read one exact mapping row and recompute its first-knowledge seal."""

        if not isinstance(mapping_record_id, UUID):
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_MAPPING_ID_INVALID"
            )
        model = (
            InstrumentReferenceMappingModel.objects.using(self._using)
            .filter(pk=mapping_record_id)
            .first()
        )
        return self._mapping_receipt(model) if model is not None else None

    def _mapping_receipt(
        self,
        model: InstrumentReferenceMappingModel,
    ) -> InstrumentReferenceMappingRecord:
        """Rebuild and validate mapping JSON, indexed columns and row seal."""

        try:
            content = mapping_content_from_payload(model.content)
            if (
                content.mapping_id != model.mapping_id
                or content.mapping_version != model.mapping_version
                or content.source_crosswalk_id != model.source_crosswalk_id
                or content.source_crosswalk_version != model.source_crosswalk_version
                or content.source_crosswalk_hash != model.source_crosswalk_hash
                or content.content_hash != model.content_hash
            ):
                raise InstrumentReferenceSnapshotPersistenceError(
                    "INSTRUMENT_REFERENCE_MAPPING_ROW_CORRUPTED"
                )
            return make_instrument_reference_mapping_record(
                content,
                mapping_record_id=model.mapping_record_id,
                recorded_at=model.recorded_at,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            if isinstance(exc, InstrumentReferenceSnapshotPersistenceError):
                raise
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_MAPPING_ROW_CORRUPTED"
            ) from exc

    def _snapshot_receipt(
        self,
        model: InstrumentReferenceSnapshotModel,
    ) -> InstrumentReferenceSnapshotRecord:
        """Rebuild a full source receipt and verify mapping, counts and seal."""

        mapping_receipt = self._mapping_receipt(model.mapping_record)
        try:
            content = snapshot_content_from_payload(
                model.snapshot_payload,
                mapping_record=mapping_receipt,
            )
            if (
                content.run_id != model.run_id
                or len(content.fetch_rounds) != model.round_count
                or content.occurrence_count != model.occurrence_count
                or content.record_count != model.record_count
                or content.content_hash != model.content_hash
            ):
                raise InstrumentReferenceSnapshotPersistenceError(
                    "INSTRUMENT_REFERENCE_SNAPSHOT_ROW_CORRUPTED"
                )
            receipt = make_instrument_reference_snapshot_record(
                content,
                snapshot_id=model.snapshot_id,
                recorded_at=model.recorded_at,
            )
            if receipt.record_digest != model.record_digest:
                raise InstrumentReferenceSnapshotPersistenceError(
                    "INSTRUMENT_REFERENCE_SNAPSHOT_ROW_CORRUPTED"
                )
            return receipt
        except (TypeError, ValueError, ValidationError) as exc:
            if isinstance(exc, InstrumentReferenceSnapshotPersistenceError):
                raise
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_SNAPSHOT_ROW_CORRUPTED"
            ) from exc

    def _verify_raw_evidence(self, content: InstrumentReferenceSnapshotContent) -> None:
        """Re-read every exact audit and retained response body before save/read."""

        for fetch_round in content.fetch_rounds:
            candidate = fetch_round.candidate
            records_by_occurrence: dict[UUID, list[InstrumentReferenceRecord]] = {
                occurrence.occurrence_id: [] for occurrence in candidate.occurrences
            }
            for record in candidate.records:
                records_by_occurrence[record.occurrence_id].append(record)
            for occurrence in candidate.occurrences:
                self._verify_occurrence(
                    occurrence,
                    candidate=candidate,
                    expected_records=tuple(records_by_occurrence[occurrence.occurrence_id]),
                )

    def _verify_occurrence(
        self,
        occurrence: InstrumentReferenceOccurrence,
        *,
        candidate: InstrumentReferenceCandidate,
        expected_records: tuple[InstrumentReferenceRecord, ...],
    ) -> None:
        """Require the stored RawAudit, RawPayload, body and parsed rows to agree."""

        reference = occurrence.raw_audit_reference
        audit = self._raw_audit_repository.get_by_id(reference.raw_audit_id)
        if not isinstance(audit, RawAudit) or not _audit_matches(
            audit,
            occurrence=occurrence,
            candidate=candidate,
        ):
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_RAW_AUDIT_MISMATCH"
            )
        try:
            audit_link = _audit_link(audit)
            payload_reference = ProviderResponsePayloadReference.from_payload(
                _mapping_value(audit_link.get("raw_payload_reference"))
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_RAW_PAYLOAD_MISMATCH"
            ) from exc
        raw_payload = self._raw_payload_reader.get_by_id(occurrence.raw_payload_id)
        if (
            raw_payload is None
            or raw_payload.payload_id != occurrence.raw_payload_id
            or raw_payload.payload_hash != occurrence.raw_payload_hash
            or payload_reference.payload_hash != occurrence.raw_payload_hash
            or payload_reference.body_sha256 != occurrence.response_body_sha256
            or payload_reference.response_completed_at != occurrence.response_completed_at
            or not payload_reference.verifies(raw_payload)
            or audit.request_params != raw_payload.request_params
            or audit.request_params_hash != _request_params_hash(raw_payload.request_params)
            or audit.schema_fingerprint != raw_payload.schema_fingerprint
            or audit.payload_size_bytes != payload_reference.body_size_bytes
            or raw_payload.provider_name != candidate.provider_contract.provider_name
            or raw_payload.dataset_key != candidate.provider_contract.dataset_key
            or raw_payload.fetched_at != occurrence.response_completed_at
        ):
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_RAW_PAYLOAD_MISMATCH"
            )
        try:
            parsed_rows = _parse_stock_basic_rows(
                raw_payload,
                payload_reference,
                provider_contract=candidate.provider_contract,
                crosswalk=candidate.crosswalk,
                exchange=occurrence.exchange,
                list_status=occurrence.list_status,
            )
            rebuilt = tuple(
                _bind_rows_to_occurrence(
                    parsed_rows,
                    occurrence=occurrence,
                    crosswalk=candidate.crosswalk,
                )
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_RAW_PAYLOAD_MISMATCH"
            ) from exc
        if len(parsed_rows) != occurrence.row_count or rebuilt != expected_records:
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_SOURCE_RECORDS_MISMATCH"
            )

    def _now(self) -> datetime:
        """Return one repository-owned aware UTC persistence instant."""

        clock = self._clock
        value = clock() if clock is not None else timezone.now()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
            or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise InstrumentReferenceSnapshotPersistenceError(
                "INSTRUMENT_REFERENCE_REPOSITORY_CLOCK_INVALID"
            )
        return value


def _audit_matches(
    audit: RawAudit,
    *,
    occurrence: InstrumentReferenceOccurrence,
    candidate: InstrumentReferenceCandidate,
) -> bool:
    """Check all raw-audit fields against the exact caller-owned occurrence."""

    link = _audit_link(audit)
    contract = candidate.provider_contract
    return (
        audit.exact_reference() == occurrence.raw_audit_reference
        and raw_audit_content_hash(audit) == occurrence.raw_audit_reference.content_hash
        and audit.provider_name == contract.provider_name
        and audit.capability == "instrument_reference"
        and audit.status == "ok"
        and audit.row_count == occurrence.row_count
        and audit.fetched_at == occurrence.response_completed_at
        and audit.response_payload_hash == occurrence.response_body_sha256
        and audit.redacted is True
        and audit.run_id == occurrence.raw_audit_reference.run_id
        and audit.ingested_run_id == occurrence.raw_audit_reference.ingested_run_id
        and audit.parser_version == "instrument-reference-raw-audit.v1"
        and set(audit.extra) == {"instrument_reference_occurrence"}
        and set(link)
        == {
            "schema",
            "occurrence_id",
            "contract_id",
            "contract_version",
            "contract_hash",
            "api_name",
            "dataset_key",
            "exchange",
            "list_status",
            "fields",
            "row_count",
            "database_alias",
            "raw_payload_reference",
        }
        and link.get("schema") == "instrument-reference-raw-audit-occurrence.v1"
        and link.get("occurrence_id") == str(occurrence.occurrence_id)
        and link.get("contract_id") == contract.contract_id
        and link.get("contract_version") == contract.contract_version
        and link.get("contract_hash") == contract.content_hash
        and link.get("api_name") == contract.api_name
        and link.get("dataset_key") == contract.dataset_key
        and link.get("exchange") == occurrence.exchange
        and link.get("list_status") == occurrence.list_status
        and link.get("fields") == contract.fields_csv
        and link.get("row_count") == occurrence.row_count
        and link.get("database_alias") == "default"
    )


def _audit_link(audit: RawAudit) -> dict[str, object]:
    """Narrow the exact instrument occurrence object from RawAudit.extra."""

    extra = audit.extra
    link = extra.get("instrument_reference_occurrence") if isinstance(extra, dict) else None
    if not isinstance(link, dict) or any(not isinstance(key, str) for key in link):
        raise InstrumentReferenceSnapshotPersistenceError("INSTRUMENT_REFERENCE_RAW_AUDIT_MISMATCH")
    return link


def _mapping_value(value: object) -> Mapping[str, object]:
    """Require a mapping-shaped reference object before parsing it."""

    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise InstrumentReferenceSnapshotPersistenceError(
            "INSTRUMENT_REFERENCE_RAW_PAYLOAD_MISMATCH"
        )
    return value


def _request_params_hash(value: object) -> str | None:
    """Compute the canonical digest used by the source's exact audit writer."""

    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        return None
    try:
        encoded = canonical_provider_response_json(value).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DjangoInstrumentReferenceSnapshotRepository",
    "InstrumentReferenceSnapshotPersistenceError",
]
