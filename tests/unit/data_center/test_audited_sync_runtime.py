"""Focused contracts for the audited Data Center runtime adapters."""

from __future__ import annotations

from contextlib import AbstractContextManager

import pytest

from apps.audit.application.data_fetch_audit import DataFetchAuditObservation
from apps.data_center.application.sync_identity import (
    SyncExecutionIdentity,
    SyncExecutionIdentityRepositoryPort,
)
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncUnitOfWork,
    DjangoSyncExecutionIdentityIssuer,
)


class _Participant:
    def __init__(self, key: str) -> None:
        self._key = key

    @property
    def unit_of_work_key(self) -> str:
        return self._key


class _AuditWriter:
    def __init__(self, alias: str) -> None:
        self.database_alias = alias

    def write(self, _observation: DataFetchAuditObservation) -> object:
        return object()


def test_participant_alias_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="participants use different transactions"):
        DjangoDataCenterSyncUnitOfWork(
            [_Participant("django:default"), _Participant("django:replica")],
            _AuditWriter("default"),
            using="default",
        )


def test_audit_writer_alias_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="audit writer alias differs"):
        DjangoDataCenterSyncUnitOfWork(
            [_Participant("django:default")],
            _AuditWriter("analytics"),
            using="default",
        )


def test_nested_atomic_use_is_rejected_without_opening_second_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = 0

    class _Atomic(AbstractContextManager[None]):
        def __enter__(self) -> None:
            nonlocal opened
            opened += 1
            return None

        def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
            return False

    def atomic(*, using: str) -> _Atomic:
        assert using == "default"
        return _Atomic()

    monkeypatch.setattr(
        "apps.data_center.infrastructure.audited_sync_runtime.transaction.atomic", atomic
    )
    unit_of_work = DjangoDataCenterSyncUnitOfWork(
        [_Participant("django:default")], _AuditWriter("default")
    )

    with unit_of_work.atomic():
        with pytest.raises(RuntimeError, match="cannot be nested"):
            with unit_of_work.atomic():
                pass

    assert opened == 1


class _Connection:
    in_atomic_block = False


class _IdentityRepository(SyncExecutionIdentityRepositoryPort):
    def __init__(self) -> None:
        self.saved: list[SyncExecutionIdentity] = []

    def persist(self, identity: SyncExecutionIdentity) -> SyncExecutionIdentity:
        self.saved.append(identity)
        return identity

    def get_by_identity_hash(self, _identity_hash: str) -> SyncExecutionIdentity | None:
        return None


def test_identity_issuer_rejects_issue_outside_active_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.data_center.infrastructure.audited_sync_runtime.transaction.get_connection",
        lambda using: _Connection(),
    )
    issuer = DjangoSyncExecutionIdentityIssuer(_IdentityRepository())

    with pytest.raises(RuntimeError, match="requires an active transaction"):
        issuer.issue(dataset_key="macro.fact", provider_name="provider-main")


def test_happy_atomic_block_exposes_active_transaction_and_resets_after_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    opened = 0

    class _Atomic(AbstractContextManager[None]):
        def __enter__(self) -> None:
            nonlocal opened
            opened += 1
            connection.in_atomic_block = True
            return None

        def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
            connection.in_atomic_block = False
            return False

    def get_connection(*, using: str) -> _Connection:
        assert using == "default"
        return connection

    monkeypatch.setattr(
        "apps.data_center.infrastructure.audited_sync_runtime.transaction.get_connection",
        get_connection,
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.audited_sync_runtime.transaction.atomic",
        lambda *, using: _Atomic(),
    )
    repository = _IdentityRepository()
    issuer = DjangoSyncExecutionIdentityIssuer(repository)
    unit_of_work = DjangoDataCenterSyncUnitOfWork(
        [_Participant("django:default")], _AuditWriter("default")
    )

    with pytest.raises(ValueError, match="sentinel"):
        with unit_of_work.atomic():
            identity = issuer.issue(dataset_key="macro.fact", provider_name="provider-main")
            assert identity.provider_name == "provider-main"
            assert connection.in_atomic_block is True
            raise ValueError("sentinel")

    assert opened == 1
    assert unit_of_work._active is False
    assert connection.in_atomic_block is False
    assert len(repository.saved) == 1
