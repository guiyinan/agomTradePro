"""Revalidate and consume one production S6 full-scope capacity import."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from django.db import DatabaseError, IntegrityError, connection

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityBinding,
    FinancialCapacityCheckpoint,
    FinancialCapacityWorkflowError,
    _manifest_sha256,
)
from apps.data_center.application.financial_scope_capacity_input import (
    FinancialScopeCapacityInputError,
    resolve_current_financial_scope_capacity_input,
)
from apps.data_center.application.financial_scope_capacity_receipt import canonical_sha256
from apps.data_center.domain.financial_scope_discovery import FinancialScopeDiscoveryError
from apps.data_center.infrastructure.financial_publication_capacity_runtime import (
    DjangoFinancialCapacityBindingSource,
    DjangoFinancialCapacityManifestSource,
)
from apps.data_center.infrastructure.financial_scope_capacity_import_runtime import (
    _load_production_ceiling,
    _production_ceiling_event_identity,
)
from apps.data_center.infrastructure.financial_scope_discovery_governance import (
    DjangoFinancialScopeManifestReviewSource,
)
from apps.data_center.infrastructure.financial_scope_manifest_current_pointer import (
    DjangoFinancialScopeManifestCurrentPointerSource,
)
from apps.data_center.infrastructure.models import (
    FinancialCapacityGovernanceRecordModel,
    FinancialScopeCapacityImportConsumptionModel,
    FinancialScopeCapacityImportModel,
    FinancialScopeManifestCurrentPointerModel,
)


class DjangoFinancialScopeCapacityImportAuthoritySource:
    """Verify current production authority and append one-time formal consumption."""

    def __init__(self) -> None:
        """Build read-only runtime, manifest, review, and ceiling sources."""

        self._binding_source = DjangoFinancialCapacityBindingSource()
        self._manifest_source = DjangoFinancialCapacityManifestSource()
        self._pointer_source = DjangoFinancialScopeManifestCurrentPointerSource()
        self._review_source = DjangoFinancialScopeManifestReviewSource()

    def load_record_sha256(self, import_id: str) -> str | None:
        """Return only a stored record digest whose payload hash and indexes agree."""

        try:
            row = FinancialScopeCapacityImportModel._default_manager.get(import_id=UUID(import_id))
        except FinancialScopeCapacityImportModel.DoesNotExist:
            return None
        except (DatabaseError, TypeError, ValueError):
            raise FinancialCapacityWorkflowError(
                "financial capacity scope import is unavailable"
            ) from None
        return row.record_sha256 if _record_matches_indexes(row) else None

    def validate_current(
        self,
        *,
        import_id: str,
        record_sha256: str,
        workflow_id: str,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
        active_universe_sha256: str,
        source_revision_sha256: str,
        now: datetime,
        expected_consumed: bool,
    ) -> str | None:
        """Re-read the import, current typed scope, dual reviews, and owner ceiling."""

        try:
            row = FinancialScopeCapacityImportModel._default_manager.get(import_id=UUID(import_id))
            return self._validate_row(
                row=row,
                record_sha256=record_sha256,
                workflow_id=workflow_id,
                binding=binding,
                manifest_sha256=manifest_sha256,
                active_universe_sha256=active_universe_sha256,
                source_revision_sha256=source_revision_sha256,
                now=now,
                expected_consumed=expected_consumed,
                lock_authorities=False,
            )
        except FinancialCapacityWorkflowError as exc:
            return str(exc)
        except (
            DatabaseError,
            FinancialScopeCapacityInputError,
            FinancialScopeDiscoveryError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return "financial_capacity_scope_import_unavailable"

    def consume_formal_start(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        now: datetime,
    ) -> None:
        """Lock and revalidate all authority before appending the start-consumption event."""

        if not connection.in_atomic_block:
            raise FinancialCapacityWorkflowError(
                "financial capacity scope import consumption requires one transaction"
            )
        import_id = checkpoint.scope_capacity_import_id
        record_sha256 = checkpoint.scope_capacity_import_record_sha256
        if (
            checkpoint.stage != "formal_publication"
            or checkpoint.status != "running"
            or import_id is None
            or record_sha256 is None
        ):
            raise FinancialCapacityWorkflowError(
                "financial capacity verified scope import is required"
            )
        try:
            row = FinancialScopeCapacityImportModel._default_manager.select_for_update().get(
                import_id=UUID(import_id)
            )
        except FinancialScopeCapacityImportModel.DoesNotExist:
            raise FinancialCapacityWorkflowError(
                "financial capacity scope import is unavailable"
            ) from None
        except (DatabaseError, TypeError, ValueError):
            raise FinancialCapacityWorkflowError(
                "financial capacity scope import is unavailable"
            ) from None
        reason = self._validate_row(
            row=row,
            record_sha256=record_sha256,
            workflow_id=checkpoint.workflow_id,
            binding=checkpoint.binding,
            manifest_sha256=checkpoint.manifest_sha256,
            active_universe_sha256=checkpoint.active_universe_sha256 or "",
            source_revision_sha256=checkpoint.source_revision_sha256,
            now=now,
            expected_consumed=False,
            lock_authorities=True,
        )
        if reason is not None:
            raise FinancialCapacityWorkflowError(reason)
        event_payload = _consumption_event_payload(
            row=row,
            checkpoint=checkpoint,
            consumed_at=now,
        )
        try:
            FinancialScopeCapacityImportConsumptionModel._default_manager.create(
                scope_import=row,
                workflow_id=checkpoint.workflow_id,
                record_sha256=record_sha256,
                event_payload=event_payload,
                event_sha256=canonical_sha256(event_payload),
                consumed_at=now,
            )
        except IntegrityError as exc:
            raise FinancialCapacityWorkflowError(
                "financial capacity scope import has already been consumed"
            ) from exc
        except DatabaseError:
            raise FinancialCapacityWorkflowError(
                "financial capacity scope import consumption failed"
            ) from None

    def _validate_row(
        self,
        *,
        row: FinancialScopeCapacityImportModel,
        record_sha256: str,
        workflow_id: str,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
        active_universe_sha256: str,
        source_revision_sha256: str,
        now: datetime,
        expected_consumed: bool,
        lock_authorities: bool,
    ) -> str | None:
        if (
            row.environment != "production"
            or row.record_sha256 != record_sha256
            or not _record_matches_indexes(row)
        ):
            return "financial_capacity_scope_import_invalid"
        payload = row.record_payload
        if not isinstance(payload, Mapping):
            return "financial_capacity_scope_import_invalid"
        stored_binding = payload.get("runtime_binding")
        if not isinstance(stored_binding, Mapping) or dict(stored_binding) != binding.to_dict():
            return "financial_capacity_scope_import_candidate_drift"
        if (
            binding.environment != "production"
            or row.candidate_sha != binding.candidate_sha
            or row.financial_provider_id != binding.provider_id
            or row.financial_provider_identity_sha256 != binding.provider_identity_sha256
        ):
            return "financial_capacity_scope_import_provider_drift"
        try:
            current_binding = self._binding_source.snapshot(
                environment="production",
                candidate_sha=row.candidate_sha,
            )
        except (FinancialCapacityWorkflowError, OSError, RuntimeError, TypeError, ValueError):
            return "financial_capacity_runtime_binding_unavailable"
        if current_binding != binding:
            return "financial_capacity_scope_import_candidate_drift"

        authority_ids = (
            row.owner_approval_id,
            row.reviewer_approval_id,
            row.production_ceiling_approval_id,
        )
        if lock_authorities:
            locked_ids = tuple(
                FinancialCapacityGovernanceRecordModel._default_manager.select_for_update()
                .filter(approval_id__in=authority_ids, revocation__isnull=True)
                .order_by("approval_id")
                .values_list("approval_id", flat=True)
            )
            if len(locked_ids) != len(set(authority_ids)):
                return "financial_capacity_scope_import_authority_revoked_or_missing"
            FinancialScopeManifestCurrentPointerModel._default_manager.select_for_update().filter(
                environment="production"
            ).first()

        try:
            scope_input = resolve_current_financial_scope_capacity_input(
                pointer_source=self._pointer_source,
                review_source=self._review_source,
                binding=binding,
                environment="production",
                now=now,
            )
        except (FinancialScopeCapacityInputError, OSError, RuntimeError, TypeError, ValueError):
            return "financial_capacity_scope_import_review_or_pointer_drift"
        reviewed = scope_input.reviewed_manifest
        candidate = reviewed.candidate
        if (
            scope_input.report_sha256 != row.scope_report_review_sha256
            or candidate.manifest_sha256 != row.scope_manifest_sha256
            or candidate.universe_sha256 != row.financial_universe_sha256
            or candidate.binding.provider_id != row.financial_provider_id
            or candidate.binding.provider_identity_sha256 != row.financial_provider_identity_sha256
            or reviewed.owner_approval_id != row.owner_approval_id
            or reviewed.owner_event_id != row.owner_event_id
            or reviewed.reviewer_approval_id != row.reviewer_approval_id
            or reviewed.reviewer_event_id != row.reviewer_event_id
        ):
            return "financial_capacity_scope_import_review_or_pointer_drift"

        receipt = payload.get("capacity_receipt")
        if not isinstance(receipt, Mapping):
            return "financial_capacity_scope_import_invalid"
        receipt_sha256 = receipt.get("receipt_sha256")
        if type(receipt_sha256) is not str or receipt_sha256 != row.receipt_sha256:
            return "financial_capacity_scope_import_invalid"
        try:
            ceiling = _load_production_ceiling(
                receipt_sha256=receipt_sha256,
                candidate_sha=row.candidate_sha,
                manifest_sha256=row.scope_manifest_sha256,
            )
            event_id, ceiling_record_sha256 = _production_ceiling_event_identity(ceiling)
        except (OSError, RuntimeError, TypeError, ValueError):
            return "financial_capacity_scope_import_ceiling_revoked_or_expired"
        if (
            ceiling.approval_id != row.production_ceiling_approval_id
            or event_id != row.production_ceiling_event_id
            or ceiling_record_sha256 != row.production_ceiling_record_sha256
        ):
            return "financial_capacity_scope_import_ceiling_drift"

        try:
            snapshot = self._manifest_source.freeze(
                stage="formal_publication",
                environment="production",
                binding=binding,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return "financial_capacity_runtime_binding_unavailable"
        if (
            _manifest_sha256(snapshot.slices) != manifest_sha256
            or snapshot.active_universe_sha256 != active_universe_sha256
            or snapshot.source_revision_sha256 != source_revision_sha256
            or snapshot.active_universe_sha256 != row.financial_universe_sha256
        ):
            return "financial_capacity_scope_drift"

        return self._validate_consumption(
            row=row,
            record_sha256=record_sha256,
            workflow_id=workflow_id,
            manifest_sha256=manifest_sha256,
            active_universe_sha256=active_universe_sha256,
            source_revision_sha256=source_revision_sha256,
            binding_payload=binding.to_dict(),
            expected_consumed=expected_consumed,
        )

    def _validate_consumption(
        self,
        *,
        row: FinancialScopeCapacityImportModel,
        record_sha256: str,
        workflow_id: str,
        manifest_sha256: str,
        active_universe_sha256: str,
        source_revision_sha256: str,
        binding_payload: Mapping[str, object],
        expected_consumed: bool,
    ) -> str | None:
        try:
            consumption = FinancialScopeCapacityImportConsumptionModel._default_manager.filter(
                scope_import=row
            ).first()
        except DatabaseError:
            return "financial_capacity_scope_import_unavailable"
        if not expected_consumed:
            return (
                "financial_capacity_scope_import_already_consumed"
                if consumption is not None
                else None
            )
        if (
            consumption is None
            or consumption.workflow_id != workflow_id
            or consumption.record_sha256 != record_sha256
            or not isinstance(consumption.event_payload, Mapping)
            or consumption.event_sha256 != canonical_sha256(consumption.event_payload)
            or consumption.event_payload
            != _consumption_event_payload(
                row=row,
                workflow_id=workflow_id,
                binding_payload=binding_payload,
                manifest_sha256=manifest_sha256,
                active_universe_sha256=active_universe_sha256,
                source_revision_sha256=source_revision_sha256,
                consumed_at=consumption.consumed_at,
            )
        ):
            return "financial_capacity_scope_import_consumption_drift"
        return None


def _record_matches_indexes(row: FinancialScopeCapacityImportModel) -> bool:
    """Verify the canonical payload digest and all denormalized import identity columns."""

    payload = row.record_payload
    if not isinstance(payload, Mapping):
        return False
    stored_sha256 = payload.get("record_sha256")
    unsigned_payload = dict(payload)
    unsigned_payload.pop("record_sha256", None)
    if (
        stored_sha256 != row.record_sha256
        or canonical_sha256(unsigned_payload) != row.record_sha256
    ):
        return False
    scalar_fields: tuple[tuple[str, object], ...] = (
        ("environment", row.environment),
        ("release_manifest_sha256", row.release_manifest_sha256),
        ("capacity_receipt_raw_sha256", row.capacity_receipt_raw_sha256),
        ("scope_report_raw_sha256", row.scope_report_raw_sha256),
        ("scope_report_review_sha256", row.scope_report_review_sha256),
        ("receipt_sha256", row.receipt_sha256),
        ("scope_pointer_sha256", row.scope_pointer_sha256),
        ("candidate_sha", row.candidate_sha),
        ("candidate_image_id", row.candidate_image_id),
        ("target_trade_date", row.target_trade_date.isoformat()),
        ("release_universe_sha256", row.release_universe_sha256),
        ("provider_identities_sha256", row.provider_identities_sha256),
        ("scope_manifest_sha256", row.scope_manifest_sha256),
        ("financial_universe_sha256", row.financial_universe_sha256),
        ("financial_provider_id", row.financial_provider_id),
        ("financial_provider_identity_sha256", row.financial_provider_identity_sha256),
        ("source_revision_sha256", row.source_revision_sha256),
        ("evidence_ledger_sha256", row.evidence_ledger_sha256),
        ("artifact_ledger_sha256", row.artifact_ledger_sha256),
        ("imported_by", row.imported_by),
        ("imported_at", row.imported_at.isoformat()),
    )
    if any(payload.get(key) != value for key, value in scalar_fields):
        return False
    review = payload.get("review")
    ceiling = payload.get("production_ceiling")
    return bool(
        isinstance(review, Mapping)
        and review.get("owner_approval_id") == row.owner_approval_id
        and review.get("owner_event_id") == row.owner_event_id
        and review.get("reviewer_approval_id") == row.reviewer_approval_id
        and review.get("reviewer_event_id") == row.reviewer_event_id
        and isinstance(ceiling, Mapping)
        and ceiling.get("approval_id") == row.production_ceiling_approval_id
        and ceiling.get("event_id") == row.production_ceiling_event_id
        and ceiling.get("record_sha256") == row.production_ceiling_record_sha256
    )


def _consumption_event_payload(
    *,
    row: FinancialScopeCapacityImportModel,
    checkpoint: FinancialCapacityCheckpoint | None = None,
    workflow_id: str | None = None,
    binding_payload: object | None = None,
    manifest_sha256: str | None = None,
    active_universe_sha256: str | None = None,
    source_revision_sha256: str | None = None,
    consumed_at: datetime,
) -> dict[str, object]:
    """Return a deterministic event binding authority, current scope, and formal workflow."""

    workflow = checkpoint.workflow_id if checkpoint is not None else workflow_id
    manifest = checkpoint.manifest_sha256 if checkpoint is not None else manifest_sha256
    universe = (
        checkpoint.active_universe_sha256 if checkpoint is not None else active_universe_sha256
    )
    source_revision = (
        checkpoint.source_revision_sha256 if checkpoint is not None else source_revision_sha256
    )
    runtime_binding: object = (
        checkpoint.binding.to_dict() if checkpoint is not None else binding_payload
    )
    if (
        workflow is None
        or manifest is None
        or universe is None
        or source_revision is None
        or not isinstance(runtime_binding, Mapping)
    ):
        raise FinancialCapacityWorkflowError(
            "financial capacity scope import consumption event is invalid"
        )
    return {
        "schema": "data-center.financial-scope-capacity-consumption.v1",
        "import_id": str(row.import_id),
        "record_sha256": row.record_sha256,
        "workflow_id": workflow,
        "candidate_sha": row.candidate_sha,
        "runtime_binding": dict(runtime_binding),
        "manifest_sha256": manifest,
        "active_universe_sha256": universe,
        "source_revision_sha256": source_revision,
        "owner_event_id": row.owner_event_id,
        "reviewer_event_id": row.reviewer_event_id,
        "production_ceiling_event_id": row.production_ceiling_event_id,
        "consumed_at": consumed_at.isoformat(),
    }
