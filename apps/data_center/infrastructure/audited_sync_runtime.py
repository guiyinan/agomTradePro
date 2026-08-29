"""Django transaction and identity adapters for audited Data Center syncs."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.data_center.application.sync_identity import (
    SyncExecutionIdentity,
    SyncExecutionIdentityRepositoryPort,
    build_sync_execution_identity,
)
from apps.data_center.application.sync_transaction import (
    DataCenterSyncAuditWriter,
    DataCenterSyncUnitOfWorkParticipant,
)


def _validated_alias(value: object) -> str:
    """Return one bounded Django alias or reject the composition."""

    if (
        type(value) is not str
        or not value
        or len(value) > 64
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError("data center sync database alias is invalid")
    return value


class DjangoDataCenterSyncClock:
    """Django timezone-backed clock for audited sync composition."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""

        value = timezone.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("data center sync clock is naive")
        return value


class DjangoSyncExecutionIdentityIssuer:
    """Issue and persist one complete identity inside the caller transaction."""

    __slots__ = ("_repository", "_using")

    def __init__(
        self,
        repository: SyncExecutionIdentityRepositoryPort,
        *,
        using: str = "default",
    ) -> None:
        self._repository = repository
        self._using = _validated_alias(using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact Django transaction identity."""

        return f"django:{self._using}"

    def issue(self, *, dataset_key: str, provider_name: str) -> SyncExecutionIdentity:
        """Generate server UUIDs and persist their exact canonical identity."""

        connection = transaction.get_connection(using=self._using)
        if not connection.in_atomic_block:
            raise RuntimeError("sync execution identity requires an active transaction")
        identity = build_sync_execution_identity(
            run_id=str(uuid4()),
            ingested_run_id=str(uuid4()),
            batch_id=str(uuid4()),
            dataset_key=dataset_key,
            provider_name=provider_name,
        )
        persisted = self._repository.persist(identity)
        if persisted != identity:
            raise ValueError("sync execution identity repository substituted the identity")
        return persisted


class DjangoDataCenterSyncUnitOfWork:
    """Validate aliases and open one outer transaction for a sync commit."""

    __slots__ = ("_active", "_participants", "_using", "_writers")

    def __init__(
        self,
        participants: Sequence[DataCenterSyncUnitOfWorkParticipant],
        audit_writer: DataCenterSyncAuditWriter,
        *,
        additional_audit_writers: Sequence[DataCenterSyncAuditWriter] = (),
        using: str = "default",
    ) -> None:
        self._using = _validated_alias(using)
        self._participants = tuple(participants)
        self._writers = (audit_writer, *tuple(additional_audit_writers))
        self._active = False
        self._validate_composition()

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact Django transaction identity."""

        return f"django:{self._using}"

    def _validate_composition(self) -> None:
        """Reject missing or cross-alias participants before any mutation."""

        if not self._participants:
            raise ValueError("audited sync unit of work requires participants")
        expected = self.unit_of_work_key
        for participant in self._participants:
            if participant.unit_of_work_key != expected:
                raise ValueError("audited sync participants use different transactions")
        for writer in self._writers:
            if writer.database_alias != self._using:
                raise ValueError("audit writer alias differs from Data Center sync alias")

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nested outer transaction for all sync mutations."""

        if self._active:
            raise RuntimeError("audited sync unit of work cannot be nested")
        self._validate_composition()
        self._active = True
        try:
            with transaction.atomic(using=self._using):
                yield
        finally:
            self._active = False


class DjangoRepairRunIdentityUnitOfWork:
    """Open the short transaction that durably issues one repair parent identity."""

    __slots__ = ("_active", "_participant", "_using")

    def __init__(
        self,
        participant: DataCenterSyncUnitOfWorkParticipant,
        *,
        using: str = "default",
    ) -> None:
        self._using = _validated_alias(using)
        self._participant = participant
        self._active = False
        self._validate_composition()

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact Django transaction identity."""

        return f"django:{self._using}"

    def _validate_composition(self) -> None:
        """Reject an identity repository bound to another database alias."""

        if self._participant.unit_of_work_key != self.unit_of_work_key:
            raise ValueError("repair identity participant uses a different transaction")

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nested transaction for parent identity persistence."""

        if self._active:
            raise RuntimeError("repair identity unit of work cannot be nested")
        self._validate_composition()
        self._active = True
        try:
            with transaction.atomic(using=self._using):
                yield
        finally:
            self._active = False


__all__ = [
    "DjangoDataCenterSyncClock",
    "DjangoDataCenterSyncUnitOfWork",
    "DjangoRepairRunIdentityUnitOfWork",
    "DjangoSyncExecutionIdentityIssuer",
]
