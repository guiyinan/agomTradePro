"""Real migrated price-limit facts, offline HTTP capture and concurrent retries."""

from __future__ import annotations

from collections.abc import Callable
from queue import Queue
from threading import Barrier, Thread

import pytest
from django.db import close_old_connections, connection, connections
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import apps.data_center.price_limit_capture_composition as capture_composition
import apps.data_center.price_limit_snapshot_composition as composition
from apps.data_center.application.price_limit_response_capture import ExactPriceLimitRequestScope
from apps.data_center.application.price_limit_snapshot import price_limit_candidate_from_capture
from apps.data_center.domain.price_limit_snapshot import PriceLimitSnapshot
from apps.data_center.infrastructure.models import PriceLimitSnapshotFactModel, RawPayloadModel
from apps.data_center.infrastructure.price_limit_snapshot_repository import (
    DjangoPriceLimitSnapshotRepository,
)
from tests.unit.data_center.test_price_limit_capture import (
    BODY,
    TRADE_DATE,
    ConfigReader,
    install_transport,
)

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])


def test_capture_to_fact_to_fresh_public_reader(
    monkeypatch: pytest.MonkeyPatch,
    record_testsuite_property: Callable[[str, object], None],
) -> None:
    """Preserve original bytes, Decimal text and unknown clocks across fresh readers."""
    session = install_transport(monkeypatch)
    monkeypatch.setattr(capture_composition, "ProviderConfigRepository", ConfigReader)
    saved = composition.build_price_limit_snapshot_capture().execute(
        provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE
    )
    row = PriceLimitSnapshotFactModel.objects.select_related("raw_payload").get(
        snapshot_id=saved.snapshot_id
    )
    assert row.raw_payload.payload["retained_response_json"].encode("utf-8") == BODY
    assert row.lower_limit_price == "9.1234567890123456789"
    assert row.upper_limit_price == "11.1234567890123456789"
    assert row.response_completed_at == saved.candidate.raw_reference.response_completed_at
    assert row.recorded_at == saved.recorded_at >= row.response_completed_at
    scope = ExactPriceLimitRequestScope(
        provider_id=19,
        provider_name="limit-fixture",
        dataset_key="equity.price.limit",
        api_name="stk_limit",
        asset_code="600000.SH",
        trade_date=TRADE_DATE,
    )

    def reject_configuration_read() -> None:
        raise AssertionError("Offline fact reader must not access provider configuration")

    monkeypatch.setattr(capture_composition, "ProviderConfigRepository", reject_configuration_read)
    cutoff = timezone.now()
    with CaptureQueriesContext(connection) as queries:
        exact = composition.build_price_limit_snapshot_reader().get_exact(
            saved.reference(), known_at=cutoff
        )
        discovered = composition.build_price_limit_snapshot_reader().discover(
            scope=scope, known_at=cutoff
        )
    assert exact == discovered == saved
    assert all(
        not query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        and "FOR UPDATE" not in query["sql"].upper()
        for query in queries
    )
    payload = exact.to_payload()
    assert payload["publication_status"] == "unpublished"
    assert payload["must_not_use_for_decision"] is payload["must_not_execute"] is True
    assert payload["currency"] is payload["observed_at"] is None
    assert payload["source_available_at"] is payload["source_published_at"] is None
    assert payload["effective_trade_date"] == TRADE_DATE.isoformat()
    assert len(session.calls) == 1
    record_testsuite_property("price_limit_fact_database", connection.settings_dict["NAME"])
    record_testsuite_property("price_limit_fact_database_vendor", connection.vendor)


def test_two_postgres_writers_replay_one_first_recorded_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real row locking and uniqueness retain one identity without refreshing its clock."""
    if connection.vendor != "postgresql":
        pytest.skip("Concurrent source-fact writes require PostgreSQL row locks")
    install_transport(monkeypatch)
    monkeypatch.setattr(capture_composition, "ProviderConfigRepository", ConfigReader)
    retained = capture_composition.build_price_limit_capture_use_case().execute(
        provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE
    )
    candidate = price_limit_candidate_from_capture(retained)
    ready = Barrier(2, timeout=15)
    outcomes: Queue[tuple[int, PriceLimitSnapshot | str]] = Queue()

    def write() -> None:
        close_old_connections()
        backend_pid = -1
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SET statement_timeout = '10000ms'")
                cursor.execute("SELECT pg_backend_pid()")
                backend_pid = cursor.fetchone()[0]
            ready.wait()
            result = DjangoPriceLimitSnapshotRepository().save(candidate)
            outcomes.put((backend_pid, result))
        except Exception as error:
            outcomes.put((backend_pid, f"{type(error).__name__}: {error}"))
        finally:
            connections["default"].close()

    workers = [Thread(target=write, daemon=True) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
    assert all(not worker.is_alive() for worker in workers)
    results = [outcomes.get(timeout=1) for _ in workers]
    assert len({pid for pid, _value in results}) == 2
    values = [value for _pid, value in results]
    assert all(isinstance(value, PriceLimitSnapshot) for value in values), results
    assert values[0] == values[1]
    assert PriceLimitSnapshotFactModel.objects.count() == 1
    assert RawPayloadModel.objects.filter(dataset_key="equity.price.limit").count() == 1
    assert DjangoPriceLimitSnapshotRepository().save(candidate) == values[0]
