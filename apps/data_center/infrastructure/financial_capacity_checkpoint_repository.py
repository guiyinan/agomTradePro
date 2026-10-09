"""Database persistence for financial publication capacity checkpoints."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.data_center.application.financial_publication_capacity import (
    FinancialCapacityCheckpoint,
    FinancialCapacityCheckpointRepository,
    FinancialCapacitySliceEvidence,
    FinancialCapacityWorkflowError,
    FinancialPublicationSlice,
    FinancialScopeCapacityImportAuthoritySource,
    _append_evidence_sha256,
    _empty_evidence_sha256,
    _evidence_manifest_sha256,
    _manifest_sha256,
)
from apps.data_center.infrastructure.financial_capacity_checkpoint_codec import (
    _checkpoint_from_payload,
    _checkpoint_to_payload,
    _evidence_from_payload,
)
from apps.data_center.infrastructure.models import (
    FinancialPublicationCapacityEvidenceModel,
    FinancialPublicationCapacityManifestItemModel,
    FinancialPublicationCapacityWorkflowModel,
)


class DjangoFinancialCapacityCheckpointRepository(FinancialCapacityCheckpointRepository):
    """Persist immutable workflow state with atomic revision compare-and-swap."""

    def __init__(
        self,
        *,
        scope_capacity_import_authority_source: (
            FinancialScopeCapacityImportAuthoritySource | None
        ) = None,
    ) -> None:
        """Inject the production S6 authority that shares formal-start transactions."""

        self._scope_capacity_import_authority_source = scope_capacity_import_authority_source

    def create(self, checkpoint: FinancialCapacityCheckpoint) -> FinancialCapacityCheckpoint:
        """Insert one initial checkpoint or reject a workflow identifier collision."""

        if (
            len(checkpoint.manifest) != checkpoint.manifest_count
            or _manifest_sha256(checkpoint.manifest) != checkpoint.manifest_sha256
            or checkpoint.evidence
            or checkpoint.evidence_count != 0
            or checkpoint.evidence_sha256 != _empty_evidence_sha256()
            or checkpoint.evidence_append is not None
        ):
            raise FinancialCapacityWorkflowError(
                "financial capacity initial checkpoint ledger is invalid"
            )
        created = _with_revision(checkpoint, 1)
        try:
            with transaction.atomic():
                FinancialPublicationCapacityWorkflowModel._default_manager.create(
                    workflow_id=created.workflow_id,
                    approval_id=_approval_id(created),
                    receipt_sha256=_consumed_receipt_sha256(created),
                    stage=created.stage,
                    status=created.status,
                    revision=created.revision,
                    checkpoint=_checkpoint_to_payload(created),
                    started_at=created.started_at,
                )
                FinancialPublicationCapacityManifestItemModel._default_manager.bulk_create(
                    [
                        FinancialPublicationCapacityManifestItemModel(
                            workflow_id=created.workflow_id,
                            ordinal=index,
                            asset_code=item.asset_code,
                            announcement_date=item.announcement_date,
                            item_sha256=_manifest_item_sha256(
                                created.workflow_id,
                                index,
                                item,
                            ),
                        )
                        for index, item in enumerate(created.manifest)
                    ],
                    batch_size=500,
                )
                if checkpoint.stage == "formal_publication" and checkpoint.status == "running":
                    authority_source = self._scope_capacity_import_authority_source
                    if authority_source is None:
                        raise FinancialCapacityWorkflowError(
                            "financial capacity scope import authority is unavailable"
                        )
                    authority_source.consume_formal_start(
                        created,
                        now=timezone.now(),
                    )
        except IntegrityError as exc:
            existing = self._read_back(checkpoint)
            if existing is not None and _same_initial_formal_start(existing, checkpoint):
                return existing
            if _approval_id(created) is not None:
                raise FinancialCapacityWorkflowError(
                    "financial capacity approval or receipt has already been consumed"
                ) from exc
            if _consumed_receipt_sha256(created) is not None:
                raise FinancialCapacityWorkflowError(
                    "financial capacity approval or receipt has already been consumed"
                ) from exc
            raise FinancialCapacityWorkflowError(
                "financial capacity workflow already exists"
            ) from exc
        except DatabaseError as exc:
            existing = self._read_back(checkpoint)
            if existing is not None and _same_initial_formal_start(existing, checkpoint):
                return existing
            raise FinancialCapacityWorkflowError(
                "financial capacity workflow commit outcome is indeterminate"
            ) from exc
        return _compact_checkpoint(created)

    def _read_back(
        self, checkpoint: FinancialCapacityCheckpoint
    ) -> FinancialCapacityCheckpoint | None:
        """Reconcile a duplicate or commit-unknown create by exact workflow identity."""

        try:
            return self.get(checkpoint.workflow_id)
        except (DatabaseError, FinancialCapacityWorkflowError, RuntimeError, TypeError, ValueError):
            return None

    def get(self, workflow_id: str) -> FinancialCapacityCheckpoint | None:
        """Read one checkpoint by its exact workflow identifier."""

        row = FinancialPublicationCapacityWorkflowModel._default_manager.filter(
            workflow_id=workflow_id
        ).first()
        if row is None:
            return None
        checkpoint = _checkpoint_from_payload(row.checkpoint)
        if (
            checkpoint.workflow_id != row.workflow_id
            or checkpoint.revision != row.revision
            or checkpoint.stage != row.stage
            or checkpoint.status != row.status
            or _approval_id(checkpoint) != row.approval_id
            or _consumed_receipt_sha256(checkpoint) != row.receipt_sha256
        ):
            raise FinancialCapacityWorkflowError(
                "financial capacity persisted checkpoint index fields do not match payload"
            )
        return checkpoint

    def manifest_item(self, workflow_id: str, index: int) -> FinancialPublicationSlice:
        """Read one immutable manifest row and verify its ordinal-specific seal."""

        if type(index) is not int or index < 0:
            raise FinancialCapacityWorkflowError("financial capacity manifest ordinal is invalid")
        row = FinancialPublicationCapacityManifestItemModel._default_manager.filter(
            workflow_id=workflow_id,
            ordinal=index,
        ).first()
        if row is None:
            raise FinancialCapacityWorkflowError("financial capacity manifest item is missing")
        item = FinancialPublicationSlice(row.asset_code, row.announcement_date)
        if row.item_sha256 != _manifest_item_sha256(workflow_id, index, item):
            raise FinancialCapacityWorkflowError("financial capacity manifest item seal is invalid")
        return item

    def stream_manifest(self, workflow_id: str) -> tuple[FinancialPublicationSlice, ...]:
        """Read one ordered manifest at a terminal boundary and verify its whole digest."""

        rows = FinancialPublicationCapacityManifestItemModel._default_manager.filter(
            workflow_id=workflow_id,
        ).order_by("ordinal")
        row_items: list[FinancialPublicationSlice] = []
        for expected_ordinal, row in enumerate(rows.iterator(chunk_size=500)):
            item = FinancialPublicationSlice(row.asset_code, row.announcement_date)
            if row.ordinal != expected_ordinal or row.item_sha256 != _manifest_item_sha256(
                workflow_id, expected_ordinal, item
            ):
                raise FinancialCapacityWorkflowError(
                    "financial capacity manifest item seal is invalid"
                )
            row_items.append(item)
        items = tuple(row_items)
        checkpoint = self.get(workflow_id)
        if checkpoint is None or len(items) != checkpoint.manifest_count:
            raise FinancialCapacityWorkflowError("financial capacity manifest count is invalid")
        if _manifest_sha256(items) != checkpoint.manifest_sha256:
            raise FinancialCapacityWorkflowError("financial capacity manifest seal is invalid")
        return items

    def stream_evidence(self, workflow_id: str) -> tuple[FinancialCapacitySliceEvidence, ...]:
        """Read and verify ordered evidence once for a receipt or activation boundary."""

        rows = FinancialPublicationCapacityEvidenceModel._default_manager.filter(
            workflow_id=workflow_id,
        ).order_by("ordinal")
        evidence_items: list[FinancialCapacitySliceEvidence] = []
        previous_sha256 = _empty_evidence_sha256()
        for expected_ordinal, row in enumerate(rows.iterator(chunk_size=500)):
            item = _evidence_from_payload(row.evidence)
            previous_sha256 = _append_evidence_sha256(
                previous_sha256,
                index=expected_ordinal,
                evidence=item,
            )
            if row.ordinal != expected_ordinal or row.evidence_sha256 != previous_sha256:
                raise FinancialCapacityWorkflowError(
                    "financial capacity evidence item seal is invalid"
                )
            evidence_items.append(item)
        evidence = tuple(evidence_items)
        checkpoint = self.get(workflow_id)
        if checkpoint is None or len(evidence) != checkpoint.evidence_count:
            raise FinancialCapacityWorkflowError("financial capacity evidence count is invalid")
        if _evidence_manifest_sha256(evidence) != checkpoint.evidence_sha256:
            raise FinancialCapacityWorkflowError("financial capacity evidence seal is invalid")
        return evidence

    def save(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        expected_revision: int,
    ) -> FinancialCapacityCheckpoint:
        """Apply one atomic checkpoint update only when the expected revision matches."""

        saved = _with_revision(checkpoint, expected_revision + 1)
        try:
            with transaction.atomic():
                expected_evidence_count: int | None = None
                expected_evidence_sha256: str | None = None
                if saved.evidence_append is not None:
                    ordinal = saved.next_slice_index - 1
                    expected_evidence_count = saved.evidence_count - 1
                    expected_evidence_sha256 = saved.evidence_previous_sha256
                    if (
                        ordinal != expected_evidence_count
                        or expected_evidence_sha256 is None
                        or _append_evidence_sha256(
                            expected_evidence_sha256,
                            index=ordinal,
                            evidence=saved.evidence_append,
                        )
                        != saved.evidence_sha256
                    ):
                        raise FinancialCapacityWorkflowError(
                            "financial capacity evidence append seal is invalid"
                        )
                    manifest_item = self.manifest_item(saved.workflow_id, ordinal)
                    if (
                        saved.evidence_append.asset_code != manifest_item.asset_code
                        or saved.evidence_append.announcement_date
                        != manifest_item.announcement_date
                    ):
                        raise FinancialCapacityWorkflowError(
                            "financial capacity evidence does not match its manifest item"
                        )
                    FinancialPublicationCapacityEvidenceModel._default_manager.create(
                        workflow_id=saved.workflow_id,
                        ordinal=ordinal,
                        evidence=saved.evidence_append.to_dict(),
                        evidence_sha256=saved.evidence_sha256,
                    )
                compact = _compact_checkpoint(saved)
                checkpoint_filter: dict[str, object] = {
                    "workflow_id": checkpoint.workflow_id,
                    "revision": expected_revision,
                }
                if expected_evidence_count is not None:
                    checkpoint_filter["checkpoint__evidence_count"] = expected_evidence_count
                    checkpoint_filter["checkpoint__evidence_sha256"] = expected_evidence_sha256
                changed = FinancialPublicationCapacityWorkflowModel._default_manager.filter(
                    **checkpoint_filter,
                ).update(
                    stage=compact.stage,
                    status=compact.status,
                    revision=compact.revision,
                    checkpoint=_checkpoint_to_payload(compact),
                    updated_at=timezone.now(),
                )
                if changed != 1:
                    raise FinancialCapacityWorkflowError(
                        "financial capacity checkpoint revision changed"
                    )
        except IntegrityError as exc:
            raise FinancialCapacityWorkflowError(
                "financial capacity evidence append already exists"
            ) from exc
        return compact


def _with_revision(
    checkpoint: FinancialCapacityCheckpoint,
    revision: int,
) -> FinancialCapacityCheckpoint:
    """Return a copy whose model and JSON revisions will remain equal."""

    from dataclasses import replace

    return replace(checkpoint, revision=revision)


def _compact_checkpoint(
    checkpoint: FinancialCapacityCheckpoint,
) -> FinancialCapacityCheckpoint:
    """Remove transient manifest/evidence material before returning a DB checkpoint."""

    return replace(
        checkpoint,
        manifest=(),
        evidence=(),
        evidence_append=None,
        evidence_previous_sha256=None,
    )


def _same_initial_formal_start(
    existing: FinancialCapacityCheckpoint,
    requested: FinancialCapacityCheckpoint,
) -> bool:
    """Match a retried formal create to the one durable import and exact frozen scope."""

    return bool(
        existing.stage == requested.stage == "formal_publication"
        and existing.workflow_id == requested.workflow_id
        and existing.binding == requested.binding
        and existing.manifest_count == requested.manifest_count
        and existing.manifest_sha256 == requested.manifest_sha256
        and existing.source_revision_sha256 == requested.source_revision_sha256
        and existing.active_universe_sha256 == requested.active_universe_sha256
        and existing.total_provider_request_budget == requested.total_provider_request_budget
        and existing.capacity_receipt == requested.capacity_receipt
        and existing.governed_ceiling == requested.governed_ceiling
        and existing.scope_capacity_import_id == requested.scope_capacity_import_id
        and existing.scope_capacity_import_record_sha256
        == requested.scope_capacity_import_record_sha256
    )


def _manifest_item_sha256(
    workflow_id: str,
    ordinal: int,
    item: FinancialPublicationSlice,
) -> str:
    """Seal one immutable manifest row to its workflow and stable ordinal."""

    payload = {
        "schema": "financial-capacity-manifest-item.v1",
        "workflow_id": workflow_id,
        "ordinal": ordinal,
        "asset_code": item.asset_code,
        "announcement_date": item.announcement_date.isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _approval_id(checkpoint: FinancialCapacityCheckpoint) -> str | None:
    """Return the one-time reviewed approval consumed by this checkpoint."""

    if checkpoint.stage == "qualification" and checkpoint.qualification_ceiling is not None:
        return checkpoint.qualification_ceiling.approval_id
    if (
        checkpoint.stage == "capacity_rehearsal"
        and checkpoint.capacity_rehearsal_ceiling is not None
    ):
        return checkpoint.capacity_rehearsal_ceiling.approval_id
    if checkpoint.stage == "formal_publication" and checkpoint.governed_ceiling is not None:
        return checkpoint.governed_ceiling.approval_id
    return None


def _consumed_receipt_sha256(checkpoint: FinancialCapacityCheckpoint) -> str | None:
    """Return a successful qualification receipt only when formal use consumes it."""

    if checkpoint.stage != "formal_publication" or checkpoint.governed_ceiling is None:
        return None
    if checkpoint.capacity_receipt is None:
        raise FinancialCapacityWorkflowError("formal financial capacity receipt is missing")
    return checkpoint.capacity_receipt.sha256


__all__ = ["DjangoFinancialCapacityCheckpointRepository"]
