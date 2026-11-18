"""Django adapters for replaying retained listing evidence and patching old rows."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC
from typing import cast
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, connections

from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.domain.asset_active_maintenance import (
    AssetActiveMaintenanceContractError,
    AssetMaintenanceTarget,
    AssetMasterMaintenancePlan,
    AssetMasterRowSnapshot,
    AssetMasterTransition,
    SourceOccurrencePin,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceOccurrence,
    InstrumentReferenceRecord,
    InstrumentReferenceSourceContractError,
)
from apps.data_center.domain.provider_response import canonical_provider_response_json
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure.models import AssetMasterModel
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    InstrumentReferenceSourceError,
    _bind_rows_to_occurrence,
    _parse_stock_basic_rows,
)

_AUDIT_LINK_KEY = "instrument_reference_occurrence"
_AUDIT_LINK_SCHEMA = "instrument-reference-raw-audit-occurrence.v1"
_MUTABLE_COLUMNS = frozenset({"is_active", "delist_date", "updated_at"})


class DjangoAssetMasterMaintenanceSourceReader:
    """Reconstruct and replay the two exact RawAudit/RawPayload stock_basic rows.

    This reader verifies retained bytes and occurrence identity. It does not
    establish legal listing status or decision/trading eligibility.
    """

    __slots__ = ("_audits", "_payloads", "_using")

    def __init__(
        self,
        *,
        audits: RawAuditRepository | None = None,
        payloads: RawLandingRepository | None = None,
        using: str = "default",
    ) -> None:
        """Bind both existing immutable evidence readers to the same DB alias."""

        if using != "default":
            raise ValueError("AssetMaster maintenance currently requires the default alias")
        self._using = using
        self._audits = audits or RawAuditRepository()
        self._payloads = payloads or RawLandingRepository()

    @property
    def unit_of_work_key(self) -> str:
        """Return the alias used by both existing RawAudit/RawPayload repositories."""

        return f"django:{self._using}"

    def read_verified(self, plan: AssetMasterMaintenancePlan) -> InstrumentReferenceCandidate:
        """Replay both pinned occurrences through the existing strict stock_basic parser."""

        contract = plan.provider_contract
        occurrences: list[InstrumentReferenceOccurrence] = []
        records: list[InstrumentReferenceRecord] = []
        pins = {pin.exchange: pin for pin in plan.source_occurrences}
        if len(pins) != 2:
            raise AssetActiveMaintenanceContractError("source_occurrence_scope_invalid")
        try:
            for exchange in ("SSE", "SZSE"):
                pin = pins[exchange]
                audit = self._audits.get_by_id(pin.raw_audit_reference.raw_audit_id)
                payload, reference, occurrence = self._read_occurrence(plan, pin, audit)
                rows = _parse_stock_basic_rows(
                    payload,
                    reference,
                    provider_contract=contract,
                    crosswalk=plan.crosswalk,
                    exchange=exchange,
                    list_status="D",
                )
                if len(rows) != pin.row_count:
                    raise AssetActiveMaintenanceContractError("source_raw_audit_row_count_mismatch")
                occurrences.append(occurrence)
                records.extend(
                    _bind_rows_to_occurrence(
                        rows,
                        occurrence=occurrence,
                        crosswalk=plan.crosswalk,
                    )
                )
            candidate = InstrumentReferenceCandidate(
                provider_contract=contract,
                crosswalk=plan.crosswalk,
                occurrences=tuple(occurrences),
                records=tuple(records),
            )
        except (AssetActiveMaintenanceContractError, InstrumentReferenceSourceContractError):
            raise
        except (InstrumentReferenceSourceError, TypeError, ValueError, KeyError) as error:
            raise AssetActiveMaintenanceContractError("source_raw_body_replay_invalid") from error
        if (
            candidate.must_not_use_for_decision is not True
            or candidate.must_not_execute is not True
            or candidate.source_observed_at is not None
            or candidate.source_available_at is not None
        ):
            raise AssetActiveMaintenanceContractError("source_candidate_decision_boundary_invalid")
        return candidate

    def _read_occurrence(
        self,
        plan: AssetMasterMaintenancePlan,
        pin: SourceOccurrencePin,
        audit: RawAudit | None,
    ) -> tuple[RawPayload, ProviderResponsePayloadReference, InstrumentReferenceOccurrence]:
        """Verify persisted audit, link, raw body, request and response clocks."""

        source_pin = pin
        contract = plan.provider_contract
        if not isinstance(audit, RawAudit):
            raise AssetActiveMaintenanceContractError("source_raw_audit_missing")
        try:
            raw_reference = audit.exact_reference()
        except (TypeError, ValueError) as error:
            raise AssetActiveMaintenanceContractError(
                "source_raw_audit_identity_invalid"
            ) from error
        link_value = audit.extra.get(_AUDIT_LINK_KEY)
        if type(link_value) is not dict:
            raise AssetActiveMaintenanceContractError("source_raw_audit_link_missing")
        link = cast(dict[str, object], link_value)
        expected_link_keys = {
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
        if set(link) != expected_link_keys:
            raise AssetActiveMaintenanceContractError("source_raw_audit_link_shape_invalid")
        if (
            raw_reference != source_pin.raw_audit_reference
            or raw_audit_content_hash(audit) != source_pin.raw_audit_reference.content_hash
            or audit.provider_name != contract.provider_name
            or audit.capability != "instrument_reference"
            or audit.status != "ok"
            or audit.redacted is not True
            or audit.response_payload_hash != source_pin.response_body_sha256
            or audit.fetched_at != source_pin.response_completed_at
            or link.get("schema") != _AUDIT_LINK_SCHEMA
            or link.get("contract_id") != contract.contract_id
            or link.get("contract_version") != contract.contract_version
            or link.get("contract_hash") != contract.content_hash
            or link.get("api_name") != contract.api_name
            or link.get("dataset_key") != contract.dataset_key
            or link.get("exchange") != source_pin.exchange
            or link.get("list_status") != "D"
            or link.get("fields") != contract.fields_csv
            or link.get("row_count") != source_pin.row_count
            or link.get("database_alias") != self._using
            or audit.row_count != source_pin.row_count
        ):
            raise AssetActiveMaintenanceContractError("source_raw_audit_pin_mismatch")
        raw_reference_payload = link.get("raw_payload_reference")
        if not isinstance(raw_reference_payload, Mapping):
            raise AssetActiveMaintenanceContractError("source_raw_payload_reference_missing")
        try:
            reference = ProviderResponsePayloadReference.from_payload(
                cast(Mapping[str, object], raw_reference_payload)
            )
        except (TypeError, ValueError) as error:
            raise AssetActiveMaintenanceContractError(
                "source_raw_payload_reference_invalid"
            ) from error
        if (
            reference.payload_id != source_pin.raw_payload_id
            or reference.payload_hash != source_pin.raw_payload_hash
            or reference.body_sha256 != source_pin.response_body_sha256
            or reference.provider_name != contract.provider_name
            or reference.dataset_key != contract.dataset_key
            or reference.response_completed_at != source_pin.response_completed_at
            or reference.original_body_retained is not True
            or reference.retained_content_encoding != "exact_original_utf8_json"
        ):
            raise AssetActiveMaintenanceContractError("source_raw_payload_pin_mismatch")
        payload = self._payloads.get_by_hash(reference.payload_hash)
        if not isinstance(payload, RawPayload) or not reference.verifies(payload):
            raise AssetActiveMaintenanceContractError("source_raw_payload_body_invalid")
        if (
            payload.payload_id != source_pin.raw_payload_id
            or payload.payload_hash != source_pin.raw_payload_hash
            or payload.request_params != audit.request_params
            or payload.fetched_at != reference.response_completed_at
        ):
            raise AssetActiveMaintenanceContractError("source_raw_payload_audit_mismatch")
        try:
            request_text = canonical_provider_response_json(audit.request_params)
            request_digest = hashlib.sha256(request_text.encode("utf-8")).hexdigest()
        except (TypeError, ValueError) as error:
            raise AssetActiveMaintenanceContractError("source_request_params_invalid") from error
        if audit.request_params_hash != request_digest:
            raise AssetActiveMaintenanceContractError("source_request_params_hash_mismatch")
        occurrence_id_value = link.get("occurrence_id")
        try:
            occurrence_id = UUID(cast(str, occurrence_id_value))
        except (TypeError, ValueError) as error:
            raise AssetActiveMaintenanceContractError("source_occurrence_id_invalid") from error
        occurrence = InstrumentReferenceOccurrence(
            occurrence_id=occurrence_id,
            exchange=source_pin.exchange,
            list_status="D",
            raw_audit_reference=raw_reference,
            raw_payload_id=reference.payload_id,
            raw_payload_hash=reference.payload_hash,
            response_body_sha256=reference.body_sha256,
            response_completed_at=reference.response_completed_at,
            row_count=source_pin.row_count,
        )
        return payload, reference, occurrence


class DjangoAssetMasterMaintenanceRepository:
    """Lock exact legacy AssetMaster rows and patch only the approved columns."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        """Bind repository operations to the explicit legacy-schema alias."""

        if using != "default":
            raise ValueError("AssetMaster maintenance currently requires the default alias")
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the explicit Django transaction identity."""

        return f"django:{self._using}"

    def lock_exact_targets(
        self,
        targets: tuple[AssetMaintenanceTarget, ...],
    ) -> tuple[AssetMasterRowSnapshot, ...]:
        """Check old columns and lock exactly the planned rows by ascending PK."""

        self._require_postgresql_outer_uow()
        self._verify_asset_master_columns()
        codes = tuple(item.code for item in targets)
        if len(codes) != 5 or len(set(codes)) != 5:
            raise AssetActiveMaintenanceContractError("asset_target_scope_invalid")
        models = tuple(
            AssetMasterModel.objects.using(self._using)
            .select_for_update()
            .filter(code__in=codes)
            .order_by("pk")
        )
        if len(models) != 5 or {model.code for model in models} != set(codes):
            raise AssetActiveMaintenanceContractError("asset_target_cardinality_invalid")
        return tuple(self._snapshot(model) for model in models)

    def deactivate_exact_targets(self, transitions: tuple[AssetMasterTransition, ...]) -> int:
        """Update only active flag, source date, and the supplied local clock."""

        self._require_postgresql_outer_uow()
        self._verify_asset_master_columns()
        if type(transitions) is not tuple or len(transitions) != 5:
            raise AssetActiveMaintenanceContractError("asset_transition_scope_invalid")
        changed = 0
        for transition in sorted(transitions, key=lambda item: item.asset_pk):
            count = (
                AssetMasterModel.objects.using(self._using)
                .filter(
                    pk=transition.asset_pk,
                    code=transition.code,
                    asset_type="stock",
                    exchange=transition.exchange,
                    is_active=True,
                )
                .update(
                    is_active=False,
                    delist_date=transition.source_delist_date,
                    updated_at=transition.updated_at,
                )
            )
            if count != 1:
                raise AssetActiveMaintenanceContractError("asset_update_identity_mismatch")
            changed += count
        return changed

    def read_exact_targets(
        self,
        targets: tuple[AssetMaintenanceTarget, ...],
    ) -> tuple[AssetMasterRowSnapshot, ...]:
        """Read all five changed records for an in-transaction exact readback."""

        self._require_postgresql_outer_uow()
        self._verify_asset_master_columns()
        codes = tuple(item.code for item in targets)
        models = tuple(
            AssetMasterModel.objects.using(self._using).filter(code__in=codes).order_by("pk")
        )
        if len(models) != 5 or {model.code for model in models} != set(codes):
            raise AssetActiveMaintenanceContractError("asset_readback_cardinality_invalid")
        return tuple(self._snapshot(model) for model in models)

    def _require_postgresql_outer_uow(self) -> None:
        """Require one READ COMMITTED outer PostgreSQL transaction before any write."""

        connection = connections[self._using]
        atomic_blocks = getattr(connection, "atomic_blocks", None)
        if (
            connection.vendor != "postgresql"
            or connection.get_autocommit()
            or not connection.in_atomic_block
            or not isinstance(atomic_blocks, list)
            or len(atomic_blocks) != 1
        ):
            raise AssetActiveMaintenanceContractError("single_outer_postgresql_uow_required")
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            isolation = cursor.fetchone()
        if isolation is None or isolation[0] != "read committed":
            raise AssetActiveMaintenanceContractError("read_committed_isolation_required")

    def _verify_asset_master_columns(self) -> None:
        """Require exact legacy columns so the preservation digest covers the full row."""

        connection = connections[self._using]
        table = AssetMasterModel._meta.db_table
        expected = {field.column for field in AssetMasterModel._meta.concrete_fields}
        try:
            with connection.cursor() as cursor:
                actual = {
                    item.name
                    for item in connection.introspection.get_table_description(cursor, table)
                }
        except DatabaseError as error:
            raise AssetActiveMaintenanceContractError("asset_master_schema_unavailable") from error
        if expected != actual:
            raise AssetActiveMaintenanceContractError("asset_master_schema_columns_mismatch")

    @classmethod
    def _snapshot(cls, model: AssetMasterModel) -> AssetMasterRowSnapshot:
        """Hash every nonmutable model column and return a typed row snapshot."""

        preserved: list[tuple[str, object]] = []
        for field in AssetMasterModel._meta.concrete_fields:
            if field.name in _MUTABLE_COLUMNS:
                continue
            column = field.column
            if type(column) is not str or not column:
                raise AssetActiveMaintenanceContractError("asset_master_column_identity_invalid")
            value = getattr(model, field.attname)
            if hasattr(value, "isoformat") and callable(value.isoformat):
                value = value.isoformat()
            elif isinstance(value, dict):
                value = value
            preserved.append((column, value))
        encoded = json.dumps(
            preserved,
            cls=DjangoJSONEncoder,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        preserved_hash = hashlib.sha256(encoded).hexdigest()
        updated_at = model.updated_at
        if updated_at.tzinfo is None or updated_at.utcoffset() != UTC.utcoffset(updated_at):
            raise AssetActiveMaintenanceContractError("asset_master_updated_at_invalid")
        return AssetMasterRowSnapshot(
            asset_pk=int(model.pk),
            code=model.code,
            asset_type=model.asset_type,
            exchange=model.exchange,
            is_active=model.is_active,
            delist_date=model.delist_date,
            updated_at=updated_at,
            preserved_state_sha256=preserved_hash,
        )


__all__ = [
    "DjangoAssetMasterMaintenanceRepository",
    "DjangoAssetMasterMaintenanceSourceReader",
]
