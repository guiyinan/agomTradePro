"""Original pair reads retain exact scope/clock evidence and cannot repair rows."""

from dataclasses import fields, replace
from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from apps.audit import retained_system_audit_pair_composition as retained_pair
from apps.audit.application.system_audit_event_outbox import (
    AppendSystemAuditEventOutboxCommand,
    AppendSystemAuditEventOutboxUseCase,
    SystemAuditEventOutboxConflict,
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
)
from apps.audit.domain.system_audit_event import AuditScopeRef, SystemAuditEvent
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_repository import _model_values
from apps.audit.retained_system_audit_pair_composition import read_retained_system_audit_pair
from tests.component.audit.test_system_audit_event_outbox_coordinator import _schema as _schema
from tests.unit.audit.test_system_audit_event import make_event

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.audit"])


def _seed():
    event = make_event()
    AppendSystemAuditEventOutboxUseCase(DjangoSystemAuditEventOutboxCoordinator()).execute(
        AppendSystemAuditEventOutboxCommand(
            event=event, expected_predecessor_hash=None, recorded_at=event.recorded_at
        )
    )
    return event


def _read(event, **changes):
    values = {
        "event_id": event.event_id,
        "event_version": event.event_version,
        "stream_id": event.stream_id,
        "scope": event.scope,
        "using": "default",
        "as_of": event.recorded_at,
    }
    values.update(changes)
    return read_retained_system_audit_pair(**values)


def _seed_successor():
    root = _seed()
    child = make_event(
        event_id="retained-audit-child",
        idempotency_key="retained-audit-child",
        sequence_no=2,
        predecessor_hash=root.content_hash,
    )
    AppendSystemAuditEventOutboxUseCase(DjangoSystemAuditEventOutboxCoordinator()).execute(
        AppendSystemAuditEventOutboxCommand(
            event=child,
            expected_predecessor_hash=root.content_hash,
            recorded_at=child.recorded_at,
        )
    )
    return root, child


def test_retained_pair_accepts_its_complete_original_stream_prefix():
    _, child = _seed_successor()
    with transaction.atomic():
        assert _read(child).event == child


def test_retained_pair_rejects_a_missing_original_predecessor_without_repair():
    if connection.vendor != "sqlite":
        pytest.skip("SQLite corruption fixture; native immutable storage remains protected")
    root, child = _seed_successor()
    with connection.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {connection.ops.quote_name(SystemAuditEventModel._meta.db_table)} "
            "WHERE event_id = %s",
            [root.event_id],
        )
    before = SystemAuditEventModel.objects.count(), SystemAuditOutboxModel.objects.count()
    with transaction.atomic(), pytest.raises(SystemAuditEventOutboxCorruption):
        _read(child)
    assert before == (SystemAuditEventModel.objects.count(), SystemAuditOutboxModel.objects.count())


def test_retained_pair_rejects_a_disconnected_but_self_consistent_predecessor():
    if connection.vendor != "sqlite":
        pytest.skip("SQLite corruption fixture; native immutable storage remains protected")
    root, child = _seed_successor()
    values = {
        field.name: getattr(root, field.name)
        for field in fields(root)
        if field.name not in {"identity_hash", "content_hash"}
    }
    values["detail"] = {"rows": 3, "source_status": "valid", "nested": {"ok": True}}
    changed = SystemAuditEvent.create(**values)
    changed.validate_hashes()
    assert changed.content_hash != child.predecessor_hash
    projected = _model_values(changed)
    assignments = ", ".join(f"{connection.ops.quote_name(name)} = %s" for name in projected)
    parameters = [
        SystemAuditEventModel._meta.get_field(name).get_db_prep_save(value, connection)
        for name, value in projected.items()
    ]
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {connection.ops.quote_name(SystemAuditEventModel._meta.db_table)} "
            f"SET {assignments} WHERE event_id = %s",
            [*parameters, root.event_id],
        )
    with transaction.atomic(), pytest.raises(SystemAuditEventOutboxCorruption):
        _read(child)


def test_retained_pair_blocks_a_prefix_above_its_bound_without_partial_validation(monkeypatch):
    _, child = _seed_successor()
    monkeypatch.setattr(retained_pair, "_MAX_RETAINED_STREAM_PREFIX", 1)
    with transaction.atomic(), pytest.raises(SystemAuditEventOutboxUnavailable):
        _read(child)


def test_original_pair_read_is_exact_and_issues_no_writes_or_savepoints():
    event = _seed()
    with transaction.atomic():
        with CaptureQueriesContext(connection) as queries:
            pair = _read(event)
        assert pair.event == event
        assert pair.audit_persisted_at == event.recorded_at
        assert pair.outbox_created_at == event.recorded_at
        assert pair.outbox_payload_sha256 == event.content_hash
        assert not any(
            item["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "SAVEPOINT"))
            for item in queries.captured_queries
        )
    assert SystemAuditEventModel.objects.count() == SystemAuditOutboxModel.objects.count() == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": AuditScopeRef("wrong-tenant", "owner:research")},
        {"stream_id": "wrong-stream"},
    ],
)
def test_original_pair_cannot_cross_scope_or_stream(changes):
    event = _seed()
    with transaction.atomic(), pytest.raises(SystemAuditEventOutboxCorruption):
        _read(event, **changes)


def test_original_pair_cannot_be_read_before_its_recorded_cutoff():
    event = _seed()
    with transaction.atomic(), pytest.raises(SystemAuditEventOutboxUnavailable):
        _read(event, as_of=event.recorded_at - timedelta(microseconds=1))


def test_missing_exact_outbox_is_blocked_without_repair(monkeypatch):
    event = _seed()
    monkeypatch.setattr(
        DjangoSystemAuditEventOutboxCoordinator,
        "get_exact_outbox_winner_targeted",
        lambda self, original: None,
    )
    with transaction.atomic(), pytest.raises(SystemAuditEventOutboxUnavailable):
        _read(event)
    assert SystemAuditEventModel.objects.count() == SystemAuditOutboxModel.objects.count() == 1


def test_retained_pair_requires_the_callers_outer_transaction_and_exact_alias():
    event = _seed()
    with pytest.raises(SystemAuditEventOutboxConflict):
        _read(event)
    with transaction.atomic(), pytest.raises(SystemAuditEventOutboxUnavailable):
        _read(event, using="missing_alias")


def test_retained_pair_rejects_a_later_persistence_clock():
    event = _seed()
    with transaction.atomic():
        pair = _read(event)
    later = replace(pair, outbox_created_at=event.recorded_at + timedelta(seconds=1))
    with pytest.raises(SystemAuditEventOutboxCorruption):
        later.verify_at_cutoff(as_of=event.recorded_at)
