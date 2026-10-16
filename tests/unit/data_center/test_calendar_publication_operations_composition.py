"""Boundaries for the server-owned calendar operation composition root."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from django.db import DEFAULT_DB_ALIAS
from rest_framework.request import Request

from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    CalendarPublicationPreview,
    CalendarPublicationPreviewIdentity,
    CapturedExchangeCalendarSnapshot,
    CaptureExchangeCalendarSnapshotIntent,
    ConfirmCalendarPublicationIntent,
    PreviewCalendarPublicationIntent,
    ReadCurrentCalendarIntent,
)
from apps.data_center.domain.exchange_calendar import ExchangeCalendarSnapshotReference
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarPublicationPointerExpectation,
)
from core.exceptions import ExternalServiceError

NOW = datetime(2026, 10, 16, 4, 0, 10, tzinfo=UTC)


class _Principal:
    """Structural placeholder for an authority context controlled by a test."""

    actor_type = "django_user"
    actor_id = "django-user:17"
    permission_codename = "publish_exchange_calendar"
    database_alias = DEFAULT_DB_ALIAS
    user_id = 17
    permission_id = 23
    verified_at = NOW

    def assert_live(self) -> None:
        """Satisfy the public principal lease protocol in composition fakes."""


_PRINCIPAL = _Principal()


class _FixedClock:
    """Return a fixed UTC instant for composition boundary checks."""

    def now(self) -> datetime:
        """Return the test's server-owned UTC cutoff."""

        return NOW


def _request() -> Request:
    """Create a typed stand-in consumed only by a patched authority boundary."""

    return cast(Request, object())


def _reference() -> ExchangeCalendarSnapshotReference:
    """Return a well-shaped exact-source reference without selecting a row."""

    return ExchangeCalendarSnapshotReference(
        snapshot_id=str(uuid4()),
        exchange="SSE",
        coverage_start=date(2026, 10, 16),
        coverage_end=date(2026, 10, 16),
        content_hash="sha256:" + "1" * 64,
        record_digest="sha256:" + "2" * 64,
        raw_payload_id=str(uuid4()),
        raw_payload_hash="sha256:" + "3" * 64,
        raw_record_digest="sha256:" + "4" * 64,
    )


def _captured() -> CapturedExchangeCalendarSnapshot:
    """Return a typed receipt representing an unpublished source capture."""

    return CapturedExchangeCalendarSnapshot(
        snapshot_reference=_reference(),
        first_seen_at=NOW,
        recorded_at=NOW,
        source_published_at=None,
    )


def _lock_factory(
    events: list[str],
    *,
    after_yield: BaseException | None = None,
) -> Callable[..., AbstractContextManager[_Principal]]:
    """Return a patched authority context that records its full lease lifetime."""

    @contextmanager
    def locked(request: Request, *, using: str) -> Iterator[_Principal]:
        assert request is _request_value
        assert using == DEFAULT_DB_ALIAS
        events.append("lock-enter")
        try:
            yield _PRINCIPAL
            events.append("lock-yield-returned")
            if after_yield is not None:
                raise after_yield
        finally:
            events.append("lock-exit")

    return locked


_request_value = _request()


class _FakeConnection:
    """Expose only transaction state inspected by the composition boundary."""

    alias = DEFAULT_DB_ALIAS

    def __init__(self, *, in_atomic_block: bool = False) -> None:
        self.in_atomic_block = in_atomic_block
        self._autocommit = not in_atomic_block
        self.atomic_blocks: list[object] = []

    def get_autocommit(self) -> bool:
        """Return the controlled autocommit state."""

        return self._autocommit


class _FakeConnections:
    """Resolve only the single configured alias used by composition."""

    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def __getitem__(self, alias: str) -> _FakeConnection:
        assert alias == DEFAULT_DB_ALIAS
        return self._connection


def _patch_fake_atomic(
    monkeypatch: pytest.MonkeyPatch,
    *,
    connection: _FakeConnection,
) -> None:
    """Install an in-memory atomic boundary without touching Django's database."""

    @contextmanager
    def atomic(*, using: str) -> Iterator[None]:
        assert using == DEFAULT_DB_ALIAS
        block = object()
        connection.in_atomic_block = True
        connection._autocommit = False
        connection.atomic_blocks.append(block)
        try:
            yield
        finally:
            connection.atomic_blocks.pop()
            connection.in_atomic_block = False
            connection._autocommit = True

    from apps.data_center import calendar_publication_operations_composition as composition

    monkeypatch.setattr(composition, "connections", _FakeConnections(connection))
    monkeypatch.setattr(composition, "transaction", SimpleNamespace(atomic=atomic))


def test_capture_uses_locked_default_and_same_outer_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Capture is composed only inside the authority-owned transaction and cutoff."""

    from apps.data_center import calendar_publication_operations_composition as composition

    events: list[str] = []
    monkeypatch.setattr(
        composition,
        "locked_calendar_publisher_for_request",
        _lock_factory(events),
    )
    monkeypatch.setattr(composition, "_ServerClock", _FixedClock)

    class _Capture:
        def execute(
            self, intent: CaptureExchangeCalendarSnapshotIntent
        ) -> CapturedExchangeCalendarSnapshot:
            assert events[-1] == "compose"
            assert intent.exchange == "SSE"
            return expected

    def compose_capture(*, known_at: datetime, using: str) -> _Capture:
        assert events == ["lock-enter"]
        assert known_at == NOW
        assert using == DEFAULT_DB_ALIAS
        events.append("compose")
        return _Capture()

    expected = _captured()
    monkeypatch.setattr(composition, "compose_calendar_snapshot_capture", compose_capture)
    actual = composition.capture_exchange_calendar_snapshot(
        _request_value,
        CaptureExchangeCalendarSnapshotIntent(
            exchange="SSE",
            coverage_start=date(2026, 10, 16),
            coverage_end=date(2026, 10, 16),
        ),
    )

    assert actual is expected
    assert events == ["lock-enter", "compose", "lock-yield-returned", "lock-exit"]


def test_publisher_operation_propagates_authority_exit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful inner result is withheld if the outer authority lease fails."""

    from apps.data_center import calendar_publication_operations_composition as composition
    from core.integration.calendar_formal_publication_audit import (
        CoreCalendarFormalPublicationAuditBridge,
    )

    events: list[str] = []
    monkeypatch.setattr(
        composition,
        "locked_calendar_publisher_for_request",
        _lock_factory(events, after_yield=ExternalServiceError("lease exit failed")),
    )
    monkeypatch.setattr(composition, "_ServerClock", _FixedClock)

    class _Preview:
        def __init__(self, *, preparation: object, clock: object, activation_ids: object) -> None:
            assert isinstance(preparation, _Repository)
            assert type(preparation.audit_port) is CoreCalendarFormalPublicationAuditBridge
            assert preparation.audit_port.database_alias == DEFAULT_DB_ALIAS
            assert isinstance(clock, _FixedClock)
            assert activation_ids is not None

        def execute(
            self,
            intent: PreviewCalendarPublicationIntent,
            *,
            principal: object,
        ) -> CalendarPublicationPreview:
            assert principal is _PRINCIPAL
            events.append("usecase-result")
            return cast(CalendarPublicationPreview, sentinel)

    class _Repository:
        def __init__(self, *, audit_port: object, using: str, clock: object) -> None:
            assert type(audit_port) is CoreCalendarFormalPublicationAuditBridge
            assert audit_port.database_alias == DEFAULT_DB_ALIAS
            assert using == DEFAULT_DB_ALIAS
            self.audit_port = audit_port

    sentinel = object()
    monkeypatch.setattr(composition, "PreviewCalendarPublicationUseCase", _Preview)
    monkeypatch.setattr(
        composition, "DjangoFormalExchangeCalendarPublicationRepository", _Repository
    )

    with pytest.raises(ExternalServiceError, match="lease exit failed"):
        composition.preview_calendar_publication(
            _request_value,
            PreviewCalendarPublicationIntent(snapshot_reference=_reference()),
        )

    assert events == ["lock-enter", "usecase-result", "lock-yield-returned", "lock-exit"]


def test_confirm_composes_the_formal_publisher_usecase_over_audited_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmation uses the existing publisher Application boundary and Audit bridge."""

    from apps.data_center import calendar_publication_operations_composition as composition
    from apps.data_center.application.formal_exchange_calendar_publication import (
        PublishExchangeCalendarSnapshotUseCase,
    )
    from core.integration.calendar_formal_publication_audit import (
        CoreCalendarFormalPublicationAuditBridge,
    )

    events: list[str] = []
    monkeypatch.setattr(
        composition,
        "locked_calendar_publisher_for_request",
        _lock_factory(events),
    )
    monkeypatch.setattr(composition, "_ServerClock", _FixedClock)

    class _Repository:
        def __init__(self, *, audit_port: object, using: str, clock: object) -> None:
            assert type(audit_port) is CoreCalendarFormalPublicationAuditBridge
            assert audit_port.database_alias == DEFAULT_DB_ALIAS
            assert using == DEFAULT_DB_ALIAS
            self.audit_port = audit_port

        def publish(self, request: object, *, principal: object) -> object:
            raise AssertionError("the fake Application should not invoke persistence")

    class _Confirm:
        def __init__(self, *, preparation: object, publisher: object, clock: object) -> None:
            assert isinstance(preparation, _Repository)
            assert isinstance(publisher, PublishExchangeCalendarSnapshotUseCase)
            assert publisher._writer is preparation
            assert clock is not None

        def execute(self, intent: ConfirmCalendarPublicationIntent, *, principal: object) -> object:
            assert principal is _PRINCIPAL
            events.append("confirm")
            return sentinel

    sentinel = object()
    monkeypatch.setattr(
        composition, "DjangoFormalExchangeCalendarPublicationRepository", _Repository
    )
    monkeypatch.setattr(composition, "ConfirmCalendarPublicationUseCase", _Confirm)
    identity = CalendarPublicationPreviewIdentity(
        dataset_key="tushare.exchange_calendar.raw",
        contract_version="1.0",
        schema_version="1.0",
        policy_identity="p2:1.0:" + "a" * 64,
        policy_version="1.0",
        calendar_response_max_age_seconds=60,
    )
    intent = ConfirmCalendarPublicationIntent(
        snapshot_reference=_reference(),
        expected_identity=identity,
        expected_pointer=CalendarPublicationPointerExpectation(
            dataset_key="tushare.exchange_calendar.raw",
            publication_key="exchange-calendar:SSE",
            pointer_id=None,
            publication_id=None,
            publication_hash=None,
            activation_id=None,
            updated_at=None,
        ),
        activation_id="calendar:activation:unit-test",
        expected_publication_hash="a" * 64,
        preview_hash="b" * 64,
    )

    actual = composition.confirm_calendar_publication(_request_value, intent)

    assert actual is sentinel
    assert events == ["lock-enter", "confirm", "lock-yield-returned", "lock-exit"]


def test_current_read_owns_one_outer_transaction_without_publisher_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read composes the exact reader inside its own transaction and has no Request input."""

    from apps.data_center import calendar_publication_operations_composition as composition
    from core.integration.calendar_formal_publication_audit import (
        CoreCalendarFormalPublicationAuditBridge,
    )

    transaction_states: list[tuple[bool, int]] = []

    class _Repository:
        def __init__(self, *, audit_port: object, using: str, clock: object) -> None:
            assert type(audit_port) is CoreCalendarFormalPublicationAuditBridge
            assert audit_port.database_alias == DEFAULT_DB_ALIAS
            assert using == DEFAULT_DB_ALIAS

        def read_current(self, query: object) -> None:
            connection = composition.connections[DEFAULT_DB_ALIAS]
            transaction_states.append((connection.in_atomic_block, len(connection.atomic_blocks)))
            return None

    monkeypatch.setattr(
        composition, "DjangoFormalExchangeCalendarPublicationRepository", _Repository
    )
    monkeypatch.setattr(composition, "_ServerClock", _FixedClock)
    fake_connection = _FakeConnection()
    _patch_fake_atomic(monkeypatch, connection=fake_connection)

    result = composition.read_current_exchange_calendar(
        ReadCurrentCalendarIntent(dataset_key="tushare.exchange_calendar.raw", exchange="SSE")
    )

    assert result is None
    assert transaction_states == [(True, 1)]
    assert not fake_connection.in_atomic_block


def test_current_read_rejects_a_caller_owned_outer_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read composition cannot silently nest inside another transaction."""

    from apps.data_center import calendar_publication_operations_composition as composition

    monkeypatch.setattr(composition, "_ServerClock", _FixedClock)
    fake_connection = _FakeConnection(in_atomic_block=True)
    _patch_fake_atomic(monkeypatch, connection=fake_connection)
    intent = ReadCurrentCalendarIntent(dataset_key="tushare.exchange_calendar.raw", exchange="SSE")

    with pytest.raises(CalendarPublicationOperationsError):
        composition.read_current_exchange_calendar(intent)
