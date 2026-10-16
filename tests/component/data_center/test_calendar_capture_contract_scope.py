"""Calendar TTL eligibility must not hide a conflicting active contract version."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from django.db import transaction
from django.test import override_settings

from apps.data_center import calendar_snapshot_capture_composition as composition
from apps.data_center.application.calendar_capture_configuration import (
    CalendarCaptureConfigurationError,
)
from apps.data_center.application.calendar_publication_operations import (
    CaptureExchangeCalendarSnapshotIntent,
)
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
)
from tests.component.data_center.test_calendar_snapshot_capture_composition import (
    DATASET_KEY,
    _calendar_body,
    _central_secrets,
    _schema,
    _write_runtime_configuration,
)
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

__all__ = ["_schema"]
pytestmark = pytest.mark.django_db(
    transaction=True, available_apps=["apps.config_center", "apps.data_center"]
)


@pytest.mark.parametrize(
    ("same_scope", "active", "must_block"),
    [(True, True, True), (False, True, False), (True, False, False)],
)
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="calendar-capture-component-key")
def test_null_ttl_contract_is_ignored_only_outside_the_active_calendar_scope(
    same_scope: bool, active: bool, must_block: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy active version in this dataset remains a real configuration conflict."""

    _write_runtime_configuration()
    original = DatasetContractModel._default_manager.get(dataset_key=DATASET_KEY)
    DatasetContractModel._default_manager.create(
        dataset_key=DATASET_KEY if same_scope else "macro.unrelated_legacy_dataset",
        contract_version="legacy-no-calendar-ttl",
        schema_version=original.schema_version,
        owner=original.owner,
        frequency=original.frequency,
        decision_critical=original.decision_critical,
        fields=original.fields,
        calendar_response_max_age_seconds=None,
        active=active,
    )
    monkeypatch.setattr(composition, "get_secrets", lambda: _central_secrets())
    session = _Session(_Response(_calendar_body()))
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)

    def capture() -> None:
        with transaction.atomic():
            configured = composition.compose_calendar_snapshot_capture(known_at=datetime.now(UTC))
            result = configured.execute(
                CaptureExchangeCalendarSnapshotIntent("SSE", date(2026, 10, 15), date(2026, 10, 16))
            )
            assert result.must_not_execute is True

    if must_block:
        with pytest.raises(CalendarCaptureConfigurationError) as failure:
            capture()
        assert failure.value.code == "CALENDAR_CAPTURE_DATASET_AMBIGUOUS"
        assert session.calls == []
        assert RawPayloadModel._default_manager.count() == 0
        assert ExchangeCalendarSnapshotFactModel._default_manager.count() == 0
    else:
        capture()
        assert len(session.calls) == 1
        assert RawPayloadModel._default_manager.count() == 1
        assert ExchangeCalendarSnapshotFactModel._default_manager.count() == 1
