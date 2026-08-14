from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Iterator
from uuid import uuid4

import pytest

from apps.audit.application.system_audit_event_outbox import (
    AppendSystemAuditEventOutboxCommand,
    AppendSystemAuditEventOutboxUseCase,
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxConflict,
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
from tests.unit.audit.test_system_audit_event import make_event


class _FakeWriter:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.commit = SystemAuditEventOutboxCommit(
            event=make_event(),
            outbox_id=uuid4(),
            event_id="evt-1",
            idempotency_key="fetch:run-1",
        )
        self.fail = fail
        self.atomic_calls = 0
        self.append_calls = 0
        self.rolled_back = False

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_calls += 1
        try:
            yield
        except Exception:
            self.rolled_back = True
            raise

    def append_and_enqueue(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        del expected_predecessor_hash, recorded_at
        self.append_calls += 1
        if self.fail is not None:
            raise self.fail
        return self.commit


def test_use_case_persists_exact_pair_inside_one_writer_uow() -> None:
    event = make_event()
    writer = _FakeWriter()
    result = AppendSystemAuditEventOutboxUseCase(writer).execute(
        AppendSystemAuditEventOutboxCommand(
            event=event,
            expected_predecessor_hash=None,
            recorded_at=event.recorded_at,
        )
    )

    assert result == writer.commit
    assert writer.atomic_calls == 1
    assert writer.append_calls == 1


@pytest.mark.parametrize(
    "failure",
    [
        SystemAuditEventOutboxUnavailable("writer unavailable"),
        SystemAuditEventOutboxConflict("identity conflict"),
    ],
)
def test_use_case_preserves_typed_writer_failures(failure: Exception) -> None:
    writer = _FakeWriter(fail=failure)
    with pytest.raises(type(failure)):
        AppendSystemAuditEventOutboxUseCase(writer).execute(
            AppendSystemAuditEventOutboxCommand(
                event=make_event(),
                expected_predecessor_hash=None,
                recorded_at=make_event().recorded_at,
            )
        )
    assert writer.rolled_back is True


def test_use_case_wraps_unknown_writer_failure_and_rolls_back() -> None:
    writer = _FakeWriter(fail=RuntimeError("database down"))
    with pytest.raises(SystemAuditEventOutboxUnavailable):
        AppendSystemAuditEventOutboxUseCase(writer).execute(
            AppendSystemAuditEventOutboxCommand(
                event=make_event(),
                expected_predecessor_hash=None,
                recorded_at=make_event().recorded_at,
            )
        )
    assert writer.rolled_back is True


def test_use_case_rejects_writer_event_substitution() -> None:
    writer = _FakeWriter()
    writer.commit = SystemAuditEventOutboxCommit(
        event=make_event(event_id="different"),
        outbox_id=uuid4(),
        event_id="different",
        idempotency_key="fetch:run-1",
    )
    with pytest.raises(SystemAuditEventOutboxCorruption):
        AppendSystemAuditEventOutboxUseCase(writer).execute(
            AppendSystemAuditEventOutboxCommand(
                event=make_event(),
                expected_predecessor_hash=None,
                recorded_at=make_event().recorded_at,
            )
        )
