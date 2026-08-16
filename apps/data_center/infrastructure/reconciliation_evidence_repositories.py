"""Repository for durable legacy/canonical reconciliation evidence."""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction

from apps.data_center.domain.reconciliation import ReconciliationEvidence

from .reconciliation_models import (
    ReconciliationEvidenceModel,
    build_reconciliation_defaults,
)


def _evidence_uuid(value: str) -> uuid.UUID:
    """Convert a domain evidence identifier into a database UUID."""

    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("reconciliation evidence_id must be a UUID") from exc


class ReconciliationEvidenceRepository:
    """Persist and query deterministic reconciliation snapshots."""

    def save(self, evidence: ReconciliationEvidence) -> ReconciliationEvidence:
        """Append one snapshot or replay the exact existing evidence.

        Reconciliation evidence is an audit record, not a mutable cache.  A
        retry with the same identity is accepted only when every persisted
        field is identical; a caller attempting to reuse an identity for a
        different snapshot receives a stable failure instead of overwriting
        history.
        """

        evidence_uuid = _evidence_uuid(evidence.evidence_id)
        defaults = build_reconciliation_defaults(evidence)
        existing = ReconciliationEvidenceModel._default_manager.filter(
            evidence_id=evidence_uuid
        ).first()
        if existing is not None:
            if not _row_matches_evidence(existing, defaults):
                raise ValueError(
                    "reconciliation evidence identity already contains a different snapshot"
                )
            return existing.to_domain()
        try:
            with transaction.atomic():
                row = ReconciliationEvidenceModel._default_manager.create(
                    evidence_id=evidence_uuid,
                    **defaults,
                )
        except IntegrityError:
            existing = ReconciliationEvidenceModel._default_manager.filter(
                evidence_id=evidence_uuid
            ).first()
            if existing is None:
                raise
            if not _row_matches_evidence(existing, defaults):
                raise ValueError(
                    "reconciliation evidence identity already contains a different snapshot"
                )
            row = existing
        return row.to_domain()

    def get_latest(self, dataset_key: str) -> ReconciliationEvidence | None:
        """Return the newest evidence for a dataset."""

        row = (
            ReconciliationEvidenceModel._default_manager.filter(dataset_key=dataset_key.strip())
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
        rows = ReconciliationEvidenceModel._default_manager.filter(
            dataset_key=dataset_key.strip()
        ).order_by("-observed_at", "-created_at")[:limit]
        return [row.to_domain() for row in rows]


def _row_matches_evidence(
    row: ReconciliationEvidenceModel,
    defaults: dict[str, object],
) -> bool:
    """Compare all immutable evidence fields while excluding ORM timestamps."""

    return all(getattr(row, field) == value for field, value in defaults.items())


__all__ = ["ReconciliationEvidenceRepository"]
