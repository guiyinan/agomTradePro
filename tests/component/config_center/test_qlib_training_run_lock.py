"""Concurrency contracts for Config Center-owned Qlib training admission."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection, connections

from apps.config_center.infrastructure.models import (
    QlibTrainingRunLockModel,
    QlibTrainingRunModel,
    SystemSettingsModel,
)
from apps.config_center.infrastructure.repositories import QlibTrainingRunRepository

pytestmark = pytest.mark.django_db(transaction=True)


def _claim_concurrently(worker_count: int = 2) -> list[bool]:
    barrier = Barrier(worker_count)

    def claim(worker_number: int) -> bool:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            run = QlibTrainingRunRepository().create_pending_run_if_idle(
                profile=None,
                requested_by=None,
                model_name=f"concurrent-model-{worker_number}",
                model_type="LGBModel",
                resolved_train_config={"worker": worker_number},
            )
            return run is not None
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(claim, range(worker_count)))


def test_training_admission_lock_is_idempotent_and_does_not_touch_system_settings() -> None:
    QlibTrainingRunLockModel._default_manager.all().delete()
    SystemSettingsModel._default_manager.all().delete()
    repository = QlibTrainingRunRepository()

    first = repository.create_pending_run_if_idle(
        profile=None,
        requested_by=None,
        model_name="first-model",
        model_type="LGBModel",
        resolved_train_config={},
    )
    second = repository.create_pending_run_if_idle(
        profile=None,
        requested_by=None,
        model_name="second-model",
        model_type="LGBModel",
        resolved_train_config={},
    )

    assert first is not None
    assert second is None
    assert QlibTrainingRunLockModel._default_manager.filter(lock_key="global").count() == 1
    assert QlibTrainingRunModel._default_manager.count() == 1
    assert SystemSettingsModel._default_manager.count() == 0


def test_sqlite_process_lock_allows_only_one_concurrent_pending_run() -> None:
    if connection.vendor != "sqlite":
        pytest.skip("SQLite fallback concurrency contract")

    results = _claim_concurrently()

    assert sum(results) == 1
    assert QlibTrainingRunModel._default_manager.count() == 1
    assert QlibTrainingRunLockModel._default_manager.filter(lock_key="global").count() == 1


def test_postgresql_row_lock_allows_only_one_cross_connection_pending_run() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row-lock visibility across two connections")

    results = _claim_concurrently()

    assert sum(results) == 1
    assert QlibTrainingRunModel._default_manager.count() == 1
    assert QlibTrainingRunLockModel._default_manager.filter(lock_key="global").count() == 1
