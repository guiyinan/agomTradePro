"""Repository for durable legacy/canonical reconciliation evidence."""

from __future__ import annotations

from django.db import IntegrityError, transaction

from apps.data_center.domain.reconciliation import ReconciliationEvidence

from ._reconciliation_evidence_repository_helpers import (
    evidence_uuid,
    row_matches_evidence,
    validated_alias,
)
from .reconciliation_evidence_unit_of_work import (
    DjangoReconciliationEvidenceUnitOfWork,
)
from .reconciliation_models import (
    ReconciliationEvidenceModel,
    build_reconciliation_defaults,
)


class ReconciliationEvidenceRepository:
    """Persist and query deterministic reconciliation snapshots."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = validated_alias(using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact Django transaction identity."""

        return f"django:{self._using}"

    def save(self, evidence: ReconciliationEvidence) -> ReconciliationEvidence:
        """Append one snapshot or replay the exact existing evidence.

        Reconciliation evidence is an audit record, not a mutable cache.  A
        retry with the same identity is accepted only when every persisted
        field is identical; a caller attempting to reuse an identity for a
        different snapshot receives a stable failure instead of overwriting
        history.
        """

        evidence_uuid_value = evidence_uuid(evidence.evidence_id)
        defaults = build_reconciliation_defaults(evidence)
        manager = ReconciliationEvidenceModel._default_manager.using(self._using)
        existing = manager.filter(evidence_id=evidence_uuid_value).first()
        if existing is not None:
            if not row_matches_evidence(existing, defaults):
                raise ValueError(
                    "reconciliation evidence identity already contains a different snapshot"
                )
            return existing.to_domain()
        try:
            with transaction.atomic(using=self._using):
                row = manager.create(
                    evidence_id=evidence_uuid_value,
                    **defaults,
                )
        except IntegrityError as exc:
            existing = manager.filter(evidence_id=evidence_uuid_value).first()
            if existing is None:
                raise
            if not row_matches_evidence(existing, defaults):
                raise ValueError(
                    "reconciliation evidence identity already contains a different snapshot"
                ) from exc
            row = existing
        return row.to_domain()

    def get_latest(self, dataset_key: str) -> ReconciliationEvidence | None:
        """Return the newest evidence for a dataset."""

        row = (
            ReconciliationEvidenceModel._default_manager.using(self._using)
            .filter(dataset_key=dataset_key.strip())
            .order_by("-observed_at", "-created_at")
            .first()
        )
        return row.to_domain() if row is not None else None

    def get_latest_for_update(self, dataset_key: str) -> ReconciliationEvidence | None:
        """Lock and return the newest dataset evidence in the active transaction."""

        connection = transaction.get_connection(using=self._using)
        if not connection.in_atomic_block:
            raise RuntimeError("reconciliation evidence lock requires an active transaction")
        row = (
            ReconciliationEvidenceModel._default_manager.using(self._using)
            .select_for_update()
            .filter(dataset_key=dataset_key.strip())
            .order_by("-observed_at", "-created_at")
            .first()
        )
        return row.to_domain() if row is not None else None

    def list_recent(
        self,
        dataset_key: str,
        *,
        limit: int = 20,
    ) -> list[ReconciliationEvidence]:
        """Return a bounded newest-first evidence history."""

        if isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit must be positive")
        rows = (
            ReconciliationEvidenceModel._default_manager.using(self._using)
            .filter(dataset_key=dataset_key.strip())
            .order_by("-observed_at", "-created_at")[:limit]
        )
        return [row.to_domain() for row in rows]


__all__ = [
    "DjangoReconciliationEvidenceUnitOfWork",
    "ReconciliationEvidenceRepository",
]
