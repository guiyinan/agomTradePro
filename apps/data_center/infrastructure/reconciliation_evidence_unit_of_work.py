"""Transaction boundary for reconciliation evidence and conflict audit writes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import transaction

from apps.data_center.application.sync_transaction import (
    DataCenterSyncUnitOfWorkParticipant,
    DataConflictAuditWriter,
)

from ._reconciliation_evidence_repository_helpers import validated_alias


class DjangoReconciliationEvidenceUnitOfWork:
    """Atomically bind reconciliation evidence to its conflict audit event."""

    __slots__ = ("_active", "_audit_writer", "_repository", "_using")

    def __init__(
        self,
        repository: DataCenterSyncUnitOfWorkParticipant,
        audit_writer: DataConflictAuditWriter,
        *,
        using: str = "default",
    ) -> None:
        self._using = validated_alias(using)
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


__all__ = ["DjangoReconciliationEvidenceUnitOfWork"]
