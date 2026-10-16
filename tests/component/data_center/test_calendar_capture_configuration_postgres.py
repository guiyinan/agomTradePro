"""Actual PostgreSQL fences for configured calendar capture, without provider RPC."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier, Event

import pytest
from django.db import close_old_connections, connection, connections, models, transaction
from django.test import override_settings

from apps.data_center import calendar_snapshot_capture_composition as composition
from apps.data_center.application.calendar_capture_configuration import (
    CalendarCaptureConfiguration,
    CalendarCaptureConfigurationError,
    SelectCalendarCaptureConfigurationUseCase,
)
from apps.data_center.application.calendar_publication_operations import (
    CaptureExchangeCalendarSnapshotIntent,
)
from apps.data_center.infrastructure.calendar_capture_configuration_repository import (
    DjangoCalendarCaptureConfigurationRepository,
)
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from tests.component.data_center.test_calendar_snapshot_capture_composition import (
    _calendar_body,
    _central_secrets,
    _schema,
    _write_runtime_configuration,
)
from tests.component.data_center.test_formal_calendar_publication_postgres import (
    _backend_pid,
    _set_worker_timeouts,
    _wait_for_exact_blocker,
)
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

__all__ = ["_schema"]
pytestmark = [
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="Requires native PostgreSQL locks"
    ),
    pytest.mark.django_db(
        transaction=True, available_apps=["apps.config_center", "apps.data_center"]
    ),
]


def _select_configuration(
    start: Barrier, pids: dict[str, int]
) -> CalendarCaptureConfiguration | tuple[str, str]:
    """Resolve actual rows in one independent backend and close it on every exit."""

    close_old_connections()
    try:
        _set_worker_timeouts()
        pids["selector"] = _backend_pid()
        start.wait(timeout=10)
        with transaction.atomic():
            try:
                return SelectCalendarCaptureConfigurationUseCase(
                    DjangoCalendarCaptureConfigurationRepository()
                ).execute(known_at=datetime.now(UTC))
            except CalendarCaptureConfigurationError as error:
                return "blocked", error.code
    finally:
        connections["default"].close()


@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="calendar-capture-component-key")
@pytest.mark.parametrize(
    ("model", "field", "expected_code"),
    [
        (DatasetContractModel, "active", "CALENDAR_CAPTURE_DATASET_MISSING"),
        (DatasetPublicationPolicyModel, "active", "CALENDAR_CAPTURE_POLICY_MISSING"),
        (DatasetProviderBindingModel, "enabled", "CALENDAR_CAPTURE_BINDING_MISSING"),
        (ProviderConfigModel, "is_active", "CALENDAR_CAPTURE_PROVIDER_INSTANCE_MISSING"),
    ],
)
def test_native_configuration_waits_for_each_catalog_dml(
    model: type[models.Model], field: str, expected_code: str
) -> None:
    """Observe each exact writer blocker and its committed configuration change."""

    _write_runtime_configuration()
    start = Barrier(2, timeout=10)
    pids: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            assert model._default_manager.update(**{field: False}) == 1
            writer_pid = _backend_pid()
            future = pool.submit(_select_configuration, start, pids)
            start.wait(timeout=10)
            assert _wait_for_exact_blocker((pids["selector"],), writer_pid) == pids["selector"]
        result = future.result(timeout=15)
    assert result == ("blocked", expected_code)
    assert RawPayloadModel._default_manager.count() == 0
    assert ExchangeCalendarSnapshotFactModel._default_manager.count() == 0


@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="calendar-capture-component-key")
def test_native_configuration_select_does_not_wait_for_an_earlier_row_lock() -> None:
    """Do not request a row lock after SHARE and create a catalog upgrade cycle."""

    ids = _write_runtime_configuration()
    start = Barrier(2, timeout=10)
    completed = Event()
    pids: dict[str, int] = {}

    def select() -> CalendarCaptureConfiguration | tuple[str, str]:
        try:
            return _select_configuration(start, pids)
        finally:
            completed.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            contract = DatasetContractModel._default_manager.select_for_update().get()
            future = pool.submit(select)
            start.wait(timeout=10)
            completed_with_row_held = completed.wait(timeout=5)
            contract.owner = "configuration-writer-after-selection"
            contract.save(update_fields=("owner",))
        result = future.result(timeout=15)
    assert completed_with_row_held
    assert type(result) is CalendarCaptureConfiguration
    assert result.provider_id == ids[0]


def _deactivate_provider(provider_id: int, start: Barrier, pids: dict[str, int]) -> int:
    """Attempt an ordinary provider DML through another real backend."""

    close_old_connections()
    try:
        _set_worker_timeouts()
        pids["writer"] = _backend_pid()
        start.wait(timeout=10)
        with transaction.atomic():
            return ProviderConfigModel._default_manager.filter(pk=provider_id).update(
                is_active=False
            )
    finally:
        connections["default"].close()


@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="calendar-capture-component-key")
def test_native_capture_holds_configuration_fence_until_retained_fact_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider change cannot cross the real retained-response capture transaction."""

    ids = _write_runtime_configuration()
    monkeypatch.setattr(composition, "get_secrets", lambda: _central_secrets())
    response = _Response(_calendar_body())
    session = _Session(response)
    monkeypatch.setattr(
        "apps.data_center.infrastructure.tushare_client._create_requests_session", lambda: session
    )
    start = Barrier(2, timeout=10)
    pids: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            configured = composition.compose_calendar_snapshot_capture(known_at=datetime.now(UTC))
            assert not session.calls
            selector_pid = _backend_pid()
            future = pool.submit(_deactivate_provider, ids[0], start, pids)
            start.wait(timeout=10)
            assert _wait_for_exact_blocker((pids["writer"],), selector_pid) == pids["writer"]
            captured = configured.execute(
                CaptureExchangeCalendarSnapshotIntent(
                    exchange="SSE",
                    coverage_start=date(2026, 10, 15),
                    coverage_end=date(2026, 10, 16),
                )
            )
            assert len(session.calls) == 1
            assert not future.done()
            assert ExchangeCalendarSnapshotFactModel._default_manager.count() == 1
        assert future.result(timeout=15) == 1
    assert not ProviderConfigModel._default_manager.get(pk=ids[0]).is_active
    fact = ExchangeCalendarSnapshotFactModel._default_manager.get(
        snapshot_id=captured.snapshot_reference.snapshot_id
    )
    raw = RawPayloadModel._default_manager.get(payload_id=fact.raw_payload_id)
    assert raw.payload["retained_response_json"].encode("utf-8") == _calendar_body()
    assert fact.first_seen_at == raw.fetched_at
    assert captured.source_published_at is None
    assert response.closed is True
