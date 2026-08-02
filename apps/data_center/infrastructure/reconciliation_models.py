"""Persistent shadow-reconciliation evidence models."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

from django.db import models

from apps.data_center.domain.reconciliation import (
    ReconciliationClassification,
    ReconciliationDifference,
    ReconciliationEvidence,
    ReconciliationReport,
)


def _json_safe(value: object | None) -> object | None:
    """Keep arbitrary comparison values JSON-safe at the persistence boundary."""

    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def _difference_payload(difference: ReconciliationDifference) -> dict[str, object | None]:
    """Serialize one typed difference without losing its category."""

    return {
        "natural_key": difference.natural_key,
        "classification": difference.classification.value,
        "legacy_value": _json_safe(difference.legacy_value),
        "canonical_value": _json_safe(difference.canonical_value),
    }


class ReconciliationEvidenceModel(models.Model):
    """Immutable-ish audit snapshot of one legacy/canonical comparison."""

    evidence_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset_key = models.CharField(max_length=160, db_index=True)
    legacy_snapshot_hash = models.CharField(max_length=128, db_index=True)
    canonical_snapshot_hash = models.CharField(max_length=128, db_index=True)
    classification_counts = models.JSONField(default=dict)
    is_clean = models.BooleanField(default=False, db_index=True)
    observed_at = models.DateTimeField(db_index=True)
    rows = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_reconciliation_evidence"
        ordering = ["-observed_at", "-created_at"]
        indexes = [
            models.Index(fields=["dataset_key", "observed_at"]),
            models.Index(fields=["dataset_key", "is_clean", "observed_at"]),
        ]

    def to_domain(self) -> ReconciliationEvidence:
        """Convert the persisted evidence into validated domain values."""

        raw_rows = self.rows
        if not isinstance(raw_rows, list):
            raise ValueError("reconciliation evidence rows must be a list")
        differences: list[ReconciliationDifference] = []
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                raise ValueError("reconciliation evidence row must be an object")
            differences.append(
                ReconciliationDifference(
                    natural_key=str(raw.get("natural_key") or ""),
                    classification=ReconciliationClassification(
                        str(raw.get("classification") or "")
                    ),
                    legacy_value=raw.get("legacy_value"),
                    canonical_value=raw.get("canonical_value"),
                )
            )
        return ReconciliationEvidence(
            evidence_id=str(self.evidence_id),
            report=ReconciliationReport(dataset_key=self.dataset_key, rows=tuple(differences)),
            legacy_snapshot_hash=self.legacy_snapshot_hash,
            canonical_snapshot_hash=self.canonical_snapshot_hash,
            observed_at=self.observed_at,
        )


def build_reconciliation_defaults(evidence: ReconciliationEvidence) -> dict[str, object]:
    """Build deterministic ORM defaults for one reconciliation evidence record."""

    return {
        "dataset_key": evidence.report.dataset_key,
        "legacy_snapshot_hash": evidence.legacy_snapshot_hash,
        "canonical_snapshot_hash": evidence.canonical_snapshot_hash,
        "classification_counts": evidence.report.counts,
        "is_clean": evidence.report.is_clean,
        "observed_at": evidence.observed_at,
        "rows": [_difference_payload(row) for row in evidence.report.rows],
    }


__all__ = ["ReconciliationEvidenceModel", "build_reconciliation_defaults"]
