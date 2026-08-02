"""Repository for durable legacy/canonical reconciliation evidence."""

from __future__ import annotations

import uuid

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
        """Upsert one evidence snapshot idempotently."""

        row, _created = ReconciliationEvidenceModel._default_manager.update_or_create(
            evidence_id=_evidence_uuid(evidence.evidence_id),
            defaults={
                **build_reconciliation_defaults(evidence),
            },
        )
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


__all__ = ["ReconciliationEvidenceRepository"]
