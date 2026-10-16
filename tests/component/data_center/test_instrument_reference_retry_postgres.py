"""An exact concurrent retry must return the committed source record receipt."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event, local
from typing import TypeVar

import pytest
from django.db import close_old_connections, connection, connections, models
from django.utils import timezone

from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    DjangoInstrumentReferenceSnapshotRepository,
)
from apps.data_center.infrastructure.models import (
    InstrumentReferenceMappingModel,
    InstrumentReferenceSnapshotModel,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from tests.component.data_center.test_instrument_reference_snapshot_repository import (
    _schema,
    persisted_source_snapshot,
)
from tests.unit.data_center.test_instrument_reference_snapshot import _mapping

__all__ = ["_schema", "persisted_source_snapshot"]
pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])
ReceiptT = TypeVar("ReceiptT", InstrumentReferenceMappingRecord, InstrumentReferenceSnapshotRecord)


@pytest.fixture(autouse=True)
def _postgresql_only() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("retry race requires two real PostgreSQL backends")


def _retry_after_winner_commit(
    model: type[models.Model],
    write: Callable[[DjangoInstrumentReferenceSnapshotRepository], ReceiptT],
    clock: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ReceiptT, ReceiptT]:
    late_preflight, winner_committed = Event(), Event()
    state = local()
    real_validate = model.full_clean

    def validate(instance: models.Model, *args: object, **kwargs: object) -> None:
        if getattr(state, "late", False):
            # Both repositories observed absence. Let the other backend commit
            # before real Django uniqueness validation runs for this retry.
            late_preflight.set()
            assert winner_committed.wait(10)
        real_validate(instance, *args, **kwargs)

    monkeypatch.setattr(model, "full_clean", validate)

    def worker(late: bool) -> tuple[int, ReceiptT]:
        close_old_connections()
        state.late = late
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SET statement_timeout = '15s'")
                cursor.execute("SHOW transaction_isolation")
                assert cursor.fetchone()[0] == "read committed"
                cursor.execute("SELECT pg_backend_pid()")
                pid = int(cursor.fetchone()[0])
            if not late:
                assert late_preflight.wait(10)
            repository = DjangoInstrumentReferenceSnapshotRepository(
                RawAuditRepository(),
                RawLandingRepository(),
                clock=lambda: clock,
            )
            result = write(repository)
            return pid, result
        finally:
            if not late:
                winner_committed.set()
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        late, winner = pool.submit(worker, True), pool.submit(worker, False)
        winner_result = winner.result(timeout=20)
        late_result = late.result(timeout=20)
    assert winner_result[0] != late_result[0]
    return winner_result[1], late_result[1]


def test_same_mapping_version_retry_returns_original_receipt_after_concurrent_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _mapping()
    winner, retried = _retry_after_winner_commit(
        InstrumentReferenceMappingModel,
        lambda repo: repo.save_mapping(content),
        timezone.now(),
        monkeypatch,
    )
    assert retried == winner
    assert InstrumentReferenceMappingModel.objects.count() == 1
    assert retried.mapping_record_id == winner.mapping_record_id
    assert retried.recorded_at == winner.recorded_at
    assert retried.record_digest == winner.record_digest


def test_same_snapshot_retry_returns_original_receipt_after_concurrent_commit(
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository, InstrumentReferenceSnapshotContent
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, content = persisted_source_snapshot
    winner, retried = _retry_after_winner_commit(
        InstrumentReferenceSnapshotModel,
        lambda repo: repo.save_snapshot(content),
        content.mapping_record.recorded_at + timedelta(seconds=10),
        monkeypatch,
    )
    assert retried == winner
    assert InstrumentReferenceSnapshotModel.objects.count() == 1
    assert retried.snapshot_id == winner.snapshot_id
    assert retried.recorded_at == winner.recorded_at
    assert retried.record_digest == winner.record_digest
