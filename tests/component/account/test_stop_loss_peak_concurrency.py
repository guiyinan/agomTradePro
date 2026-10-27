"""Native PostgreSQL connections must not overwrite a newer trailing peak."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Event

import pytest
from django.contrib.auth.models import User
from django.db import connection, connections
from django.utils import timezone

from apps.account.application.stop_loss_use_cases import AutoStopLossUseCase, StopLossCheckOutput
from apps.account.infrastructure.models import StopLossConfigModel
from apps.account.infrastructure.repositories import StopLossRepository
from tests.integration.account.test_stop_loss_execution_contract import (
    _account_ledger_snapshot,
    _create_position,
    _StaticMarketPriceService,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires native PostgreSQL"),
]


def test_two_connections_cannot_overwrite_a_committed_newer_trailing_peak() -> None:
    """Both readers see ten; twelve commits before the stale eleven observation."""

    assert_native_postgres_test_database()
    owner = User.objects.create_user(username="native-trailing-peak-owner")
    position = _create_position(owner, name="NativeTrailingPeak", shares=1000)
    old_clock = timezone.now() - timedelta(minutes=3)
    config = StopLossConfigModel.objects.create(
        position=position,
        stop_loss_type="trailing",
        stop_loss_pct=0.2,
        trailing_stop_pct=0.1,
        highest_price=Decimal("10.0000"),
        highest_price_updated_at=old_clock,
        status="active",
    )
    ledger_before = _account_ledger_snapshot(position.portfolio)
    both_read = Barrier(2, timeout=10)
    newer_committed = Event()

    class CapturingRepository(StopLossRepository):
        def get_active_stop_loss_configs(self, user_id=None):
            rows = super().get_active_stop_loss_configs(user_id=user_id)
            assert len(rows) == 1
            assert rows[0]["highest_price"] == Decimal("10.0000")
            return rows

    def worker(*, newer: bool) -> tuple[int, StopLossCheckOutput]:
        connections.close_all()
        try:
            assert_native_postgres_test_database()
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pid = cursor.fetchone()[0]

            def synchronize_observation() -> None:
                both_read.wait()
                if not newer:
                    assert newer_committed.wait(10), "Newer observation did not finish"

            results = AutoStopLossUseCase(
                market_data_service=_StaticMarketPriceService(
                    "12.0000" if newer else "11.0000",
                    old_clock + timedelta(minutes=2 if newer else 1),
                    synchronize_observation,
                ),
                stop_loss_repo=CapturingRepository(),
            ).check_and_execute_stop_loss(user_id=owner.pk)
            assert len(results) == 1
            return pid, results[0]
        finally:
            if newer:
                newer_committed.set()
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        newer_future = pool.submit(worker, newer=True)
        older_future = pool.submit(worker, newer=False)
        newer_pid, newer_result = newer_future.result(timeout=30)
        older_pid, older_result = older_future.result(timeout=30)

    assert newer_pid != older_pid
    assert newer_result.check_status == "evaluated"
    assert older_result.check_status == "unavailable"
    assert older_result.reason_code == "stop_loss_peak_observation_changed"
    assert older_result.triggered is False
    config.refresh_from_db()
    assert config.highest_price == Decimal("12.0000")
    assert config.highest_price_updated_at == old_clock + timedelta(minutes=2)
    assert _account_ledger_snapshot(position.portfolio) == ledger_before
