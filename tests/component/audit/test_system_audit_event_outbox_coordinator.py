from __future__ import annotations

import os
from datetime import UTC, datetime

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_system_event")
django.setup()

from django.db import connection

from apps.audit.application.system_audit_event_outbox import (
    AppendSystemAuditEventOutboxCommand,
    AppendSystemAuditEventOutboxUseCase,
    SystemAuditEventOutboxUnavailable,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
)
from tests.unit.audit.test_system_audit_event import make_event

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime(2026, 8, 14, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object):
    """Create the two schema-only tables for this isolated component."""

    blocker = django_db_blocker
    with blocker.unblock():  # type: ignore[attr-defined]
        created: list[type[object]] = []
        existing = set(connection.introspection.table_names())
        for model in (SystemAuditEventModel, SystemAuditOutboxModel):
            if model._meta.db_table not in existing:
                with connection.schema_editor() as editor:
                    editor.create_model(model)
                created.append(model)
        yield
        for model in reversed(created):
            with connection.schema_editor() as editor:
                editor.delete_model(model)


def test_event_and_outbox_commit_as_one_exact_pair() -> None:
    event = make_event()
    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    result = AppendSystemAuditEventOutboxUseCase(coordinator).execute(
        AppendSystemAuditEventOutboxCommand(
            event=event,
            expected_predecessor_hash=None,
            recorded_at=event.recorded_at,
        )
    )

    assert result.event == event
    assert result.outbox_id is not None
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1
    outbox = SystemAuditOutboxModel._default_manager.get()
    assert outbox.event_id == event.event_id
    assert outbox.payload_hash == event.content_hash
    assert outbox.created_at == event.recorded_at


def test_exact_retry_replays_without_duplicate_rows() -> None:
    event = make_event()
    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    command = AppendSystemAuditEventOutboxCommand(
        event=event,
        expected_predecessor_hash=None,
        recorded_at=event.recorded_at,
    )

    first = AppendSystemAuditEventOutboxUseCase(coordinator).execute(command)
    second = AppendSystemAuditEventOutboxUseCase(coordinator).execute(command)

    assert second == first
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1


def test_outbox_failure_rolls_back_event_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = make_event()

    def fail_enqueue(
        _repository: DjangoSystemAuditOutboxRepository,
        _event: object,
        *,
        available_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> object:
        del available_at, created_at
        raise RuntimeError("simulated outbox failure")

    monkeypatch.setattr(DjangoSystemAuditOutboxRepository, "enqueue", fail_enqueue)
    with pytest.raises(SystemAuditEventOutboxUnavailable):
        AppendSystemAuditEventOutboxUseCase(DjangoSystemAuditEventOutboxCoordinator()).execute(
            AppendSystemAuditEventOutboxCommand(
                event=event,
                expected_predecessor_hash=None,
                recorded_at=event.recorded_at,
            )
        )

    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0
