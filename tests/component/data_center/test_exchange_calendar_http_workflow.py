"""Reference-calendar journey with only the outbound HTTP boundary replaced."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import cast

import pytest

from apps.data_center.application.exchange_calendar import (
    IngestExchangeCalendarSnapshotUseCase,
    ReadExchangeCalendarSnapshotUseCase,
    ReadNextExchangeCalendarSessionUseCase,
)
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.exchange_calendar_repository import (
    DjangoExchangeCalendarSnapshotRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
)
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.tushare_exchange_calendar_source import (
    TushareCalendarClientPort,
    TushareExchangeCalendarSource,
)
from tests.support.isolated_schema import isolated_schema
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((RawPayloadModel, ExchangeCalendarSnapshotFactModel)):
            yield


def test_http_capture_to_exact_calendar_and_next_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real client, retainer, source, ORM and application agree on one response."""

    body = (
        b'{ "code":0,"msg":null,"data":{'
        b'"fields":["exchange","cal_date","is_open","pretrade_date"],'
        b'"items":[["SSE","20261015",1,"20261014"],'
        b'["SSE","20261016","1","20261015"],'
        b'["SSE","20261017",0,"20261016"],'
        b'["SSE","20261018","0","20261016"]]}}\n'
    )
    response = _Response(body)
    session = _Session(response)
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    raw_repository = RawLandingRepository()
    retainer = RetainProviderResponsePayloadUseCase(raw_repository)
    dataset_key = "tushare.exchange_calendar.raw"
    client = tushare_client.create_tushare_pro_client(
        token="fixture-calendar-key",
        http_url="https://market.example.test/pro",
        request_mode=tushare_client.TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
        dataset_key=dataset_key,
        provider_response_handler=retainer.execute,
    )
    source = TushareExchangeCalendarSource(
        cast(TushareCalendarClientPort, client), raw_repository, dataset_key=dataset_key
    )
    repository = DjangoExchangeCalendarSnapshotRepository()
    snapshot = IngestExchangeCalendarSnapshotUseCase(source, repository).execute(
        "SSE", date(2026, 10, 15), date(2026, 10, 18)
    )
    known_at = datetime.now(UTC)
    reader = ReadExchangeCalendarSnapshotUseCase(repository)
    reference = snapshot.reference()
    restored = reader.execute(reference, known_at=known_at)
    next_session = ReadNextExchangeCalendarSessionUseCase(reader).execute(
        reference, after_date=date(2026, 10, 15), known_at=known_at
    )

    assert restored == snapshot
    assert next_session.session_date == date(2026, 10, 16)
    assert next_session.snapshot_reference == reference
    assert [day.is_open for day in snapshot.days] == [True, True, False, False]
    assert snapshot.source_published_at is None
    payload = snapshot.to_payload()
    assert payload["publication_status"] == "unpublished"
    assert payload["must_not_use_for_decision"] is True
    assert payload["must_not_execute"] is True
    assert payload["blocked_reason"] == "exchange_calendar_unpublished_reference"
    assert snapshot.first_seen_at <= snapshot.recorded_at <= known_at
    assert snapshot.raw_reference.body_sha256 == sha256(body).hexdigest()
    raw = raw_repository.get_by_hash(snapshot.raw_reference.payload_hash)
    assert raw is not None
    assert raw.payload["retained_response_json"].encode("utf-8") == body
    assert snapshot.first_seen_at == raw.fetched_at
    assert RawPayloadModel.objects.count() == 1
    assert ExchangeCalendarSnapshotFactModel.objects.count() == 1
    assert response.closed is True
    assert len(session.calls) == 1
