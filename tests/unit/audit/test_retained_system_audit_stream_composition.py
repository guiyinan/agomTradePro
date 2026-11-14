"""Targeted stream reads retain real codecs and the actual outer-read gate."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from apps.audit import retained_system_audit_stream_composition as stream
from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxConflict,
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure import system_audit_event_outbox_coordinator as coordinator
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
)
from apps.audit.infrastructure.system_audit_repository import _model_values
from tests.unit.audit.test_system_audit_event import NOW, make_event


@pytest.fixture
def original_stream(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Use original hash-valid ORM payloads without claiming a database acceptance run."""
    first = make_event()
    second = make_event(
        sequence_no=2,
        predecessor_hash=first.content_hash,
        event_id="evt-2",
        idempotency_key="fetch:run-2",
    )
    events = (first, second)
    rows = [SystemAuditEventModel(**_model_values(event)) for event in events]
    records = {}
    outbox_repository = DjangoSystemAuditOutboxRepository(using="default")
    from apps.audit.infrastructure.system_audit_event_codec import encode

    for event in events:
        row = SystemAuditOutboxModel(
            outbox_id=uuid4(),
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            payload_hash=event.content_hash,
            payload=encode(event),
            status="pending",
            attempt_count=0,
            available_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        records[event.event_id] = outbox_repository._restore(row)
    connection = SimpleNamespace(
        in_atomic_block=True, atomic_blocks=[object()], get_autocommit=lambda: False
    )
    monkeypatch.setattr(coordinator, "connections", {"default": connection})
    active = []

    def lock_streams(self, stream_ids):
        assert self._read_active and not self._active
        assert stream_ids == (first.stream_id,)
        active.append(self)

    monkeypatch.setattr(
        coordinator.DjangoSystemAuditEventOutboxCoordinator, "lock_streams", lock_streams
    )
    query = Mock()
    query.using.return_value.select_for_update.return_value.filter.return_value.order_by.return_value.__getitem__ = Mock(
        side_effect=lambda selected: rows[selected]
    )
    monkeypatch.setattr(stream, "SystemAuditEventModel", SimpleNamespace(_base_manager=query))

    def winners(self, selected):
        assert active[-1]._read_active and not active[-1]._active
        return {
            event.event_id: records[event.event_id]
            for event in selected
            if event.event_id in records
        }

    monkeypatch.setattr(DjangoSystemAuditOutboxRepository, "get_identity_winners_targeted", winners)
    return SimpleNamespace(
        events=events, rows=rows, records=records, query=query, active=active, connection=connection
    )


def _read(fixture: SimpleNamespace):
    first = fixture.events[0]
    return stream.read_retained_system_audit_stream(
        stream_id=first.stream_id,
        scope=first.scope,
        using="default",
        as_of=NOW,
    )


def test_reads_complete_original_pairs_with_only_exact_stream_selector(original_stream):
    result = _read(original_stream)
    assert tuple(pair.event for pair in result) == original_stream.events
    assert all(pair.outbox_created_at == NOW and pair.audit_persisted_at == NOW for pair in result)
    original_stream.query.using.assert_called_once_with("default")
    original_stream.query.using.return_value.select_for_update.return_value.filter.assert_called_once_with(
        stream_id=original_stream.events[0].stream_id,
        recorded_at__lte=NOW,
    )
    assert not original_stream.active[0]._read_active and not original_stream.active[0]._active


@pytest.mark.parametrize(
    "fault",
    [
        "missing_root",
        "wrong_predecessor",
        "foreign_scope",
        "header_tamper",
        "missing_outbox",
        "changed_outbox",
        "late_outbox",
        "oversized",
    ],
)
def test_incomplete_or_changed_original_stream_never_returns_partial_pairs(
    original_stream, monkeypatch, fault
):
    fixture = original_stream
    if fault == "missing_root":
        fixture.rows.pop(0)
    elif fault == "wrong_predecessor":
        event = make_event(
            sequence_no=2,
            predecessor_hash="a" * 64,
            event_id="evt-2",
            idempotency_key="fetch:run-2",
        )
        fixture.rows[1] = SystemAuditEventModel(**_model_values(event))
    elif fault == "foreign_scope":
        event = make_event(
            sequence_no=2,
            predecessor_hash=fixture.events[0].content_hash,
            event_id="evt-2",
            idempotency_key="fetch:run-2",
            scope=AuditScopeRef("other", "other"),
        )
        fixture.rows[1] = SystemAuditEventModel(**_model_values(event))
    elif fault == "header_tamper":
        fixture.rows[1].content_hash = "b" * 64
    elif fault == "missing_outbox":
        del fixture.records["evt-2"]
    elif fault == "changed_outbox":
        fixture.records["evt-2"] = fixture.records["evt-1"]
    elif fault == "late_outbox":
        fixture.records["evt-2"] = replace(
            fixture.records["evt-2"], created_at=NOW + timedelta(seconds=1)
        )
    else:
        monkeypatch.setattr(stream, "_MAX_STREAM_EVENTS", 1)
    with pytest.raises((SystemAuditEventOutboxCorruption, SystemAuditEventOutboxUnavailable)):
        _read(fixture)
    assert not fixture.active[0]._read_active and not fixture.active[0]._active


def test_real_outer_read_gate_rejects_nested_caller(original_stream):
    original_stream.connection.atomic_blocks.append(object())
    with pytest.raises(SystemAuditEventOutboxConflict, match="outermost"):
        _read(original_stream)
    original_stream.query.using.assert_not_called()


def test_empty_selected_stream_is_empty_without_other_stream_fallback(original_stream):
    original_stream.rows.clear()
    assert _read(original_stream) == ()


def test_bound_applies_to_whole_stream_across_small_outbox_batches(original_stream, monkeypatch):
    monkeypatch.setattr(stream, "_OUTBOX_BATCH_SIZE", 1)
    assert len(_read(original_stream)) == 2
