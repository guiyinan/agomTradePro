"""Repository for durable legacy/canonical reconciliation evidence."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from django.db import IntegrityError, transaction

from apps.data_center.application.sync_transaction import DataConflictAuditWriter
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


def _validated_alias(value: object) -> str:
    """Return one bounded Django database alias or raise."""

    if (
        type(value) is not str
        or not value
        or len(value) > 64
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError("reconciliation database alias is invalid")
    return value


class ReconciliationEvidenceRepository:
    """Persist and query deterministic reconciliation snapshots."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = _validated_alias(using)

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

        evidence_uuid = _evidence_uuid(evidence.evidence_id)
        defaults = build_reconciliation_defaults(evidence)
        manager = ReconciliationEvidenceModel._default_manager.using(self._using)
        existing = manager.filter(evidence_id=evidence_uuid).first()
        if existing is not None:
            if not _row_matches_evidence(existing, defaults):
                raise ValueError(
                    "reconciliation evidence identity already contains a different snapshot"
                )
            return existing.to_domain()
        try:
            with transaction.atomic(using=self._using):
                row = manager.create(
                    evidence_id=evidence_uuid,
                    **defaults,
                )
        except IntegrityError:
            existing = manager.filter(evidence_id=evidence_uuid).first()
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


class DjangoReconciliationEvidenceUnitOfWork:
    """Atomically bind reconciliation evidence to its conflict audit event."""

    __slots__ = ("_active", "_audit_writer", "_repository", "_using")

    def __init__(
        self,
        repository: ReconciliationEvidenceRepository,
        audit_writer: DataConflictAuditWriter,
        *,
        using: str = "default",
    ) -> None:
        self._using = _validated_alias(using)
        self._repository = repository
        self._audit_writer = audit_writer
        self._active = False
        self._validate_composition()

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact Django transaction identity."""

        return f"django:{self._using}"

    def _validate_composition(self) -> None:
        """Reject a repository or writer bound to another database alias."""

        if self._repository.unit_of_work_key != self.unit_of_work_key:
            raise ValueError("reconciliation repository uses a different transaction")
        if self._audit_writer.database_alias != self._using:
            raise ValueError("conflict audit writer uses a different database alias")

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nested outer transaction for evidence and audit writes."""

        if self._active:
            raise RuntimeError("reconciliation evidence unit of work cannot be nested")
        self._validate_composition()
        self._active = True
        try:
            with transaction.atomic(using=self._using):
                yield
        finally:
            self._active = False


def _row_matches_evidence(
    row: ReconciliationEvidenceModel,
    defaults: dict[str, object],
) -> bool:
    """Compare all immutable evidence fields while excluding ORM timestamps."""

    return all(getattr(row, field) == value for field, value in defaults.items())


__all__ = [
    "DjangoReconciliationEvidenceUnitOfWork",
    "ReconciliationEvidenceRepository",
]
