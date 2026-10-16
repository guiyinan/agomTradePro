"""SQLite persistence for immutable source-bound exchange calendar snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256

import pytest
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.infrastructure.exchange_calendar_repository import (
    DjangoExchangeCalendarSnapshotRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
)
from apps.data_center.infrastructure.models import (
    ExchangeCalendarSnapshotFactModel as PublicSnapshotModel,
)
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.tushare_client import TushareResponseEvidence
from apps.data_center.infrastructure.tushare_exchange_calendar_source import (
    TushareExchangeCalendarSource,
)
from core.exceptions import DataFetchError
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])

_FIELDS = "exchange,cal_date,is_open,pretrade_date"
_DATASET = "tushare.exchange_calendar.raw"
_EXCHANGE = "SSE"
_START = date(2026, 10, 15)
_END = date(2026, 10, 18)
_ROWS: list[list[object]] = [
    ["SSE", "20261015", 1, "20261014"],
    ["SSE", "20261016", 1, "20261015"],
    ["SSE", "20261017", 0, "20261016"],
    ["SSE", "20261018", 0, "20261016"],
]


@pytest.fixture(autouse=True)
def _snapshot_schema(django_db_blocker: object) -> Iterator[None]:
    """Create only the raw source row and the calendar fact table."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((RawPayloadModel, ExchangeCalendarSnapshotFactModel)):
            yield


class _CapturedFrame:
    """Supply the public evidence attribute of a Tushare capture wrapper."""

    def __init__(self, response_evidence: TushareResponseEvidence) -> None:
        self.response_evidence = response_evidence


class _CapturedClient:
    """Persist one prepared response and expose its exact transport witness."""

    def __init__(self, reference: object, body_sha256: str, completed_at: datetime) -> None:
        self.reference = reference
        self.body_sha256 = body_sha256
        self.completed_at = completed_at

    def trade_cal(self, **kwargs: object) -> _CapturedFrame:
        return _CapturedFrame(
            TushareResponseEvidence(
                body_sha256=self.body_sha256,
                response_completed_at=self.completed_at,
                raw_payload_reference=self.reference,  # type: ignore[arg-type]
            )
        )


def _candidate():
    """Retain and parse one exact test response using the real raw repository."""

    body = json.dumps(
        {
            "code": 0,
            "msg": None,
            "data": {"fields": _FIELDS.split(","), "items": _ROWS},
        },
        separators=(",", ":"),
    ).encode("utf-8")
    completed_at = datetime.now(UTC)
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=completed_at,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    request_params: dict[str, object] = {
        "api_name": "trade_cal",
        "fields": _FIELDS,
        "params": {
            "exchange": _EXCHANGE,
            "start_date": _START.strftime("%Y%m%d"),
            "end_date": _END.strftime("%Y%m%d"),
        },
    }
    raw_repository = RawLandingRepository()
    reference = RetainProviderResponsePayloadUseCase(raw_repository).execute(
        capture,
        provider_name="tushare",
        dataset_key=_DATASET,
        api_name="trade_cal",
        request_params=request_params,
    )
    client = _CapturedClient(reference, capture.body_sha256, completed_at)
    source = TushareExchangeCalendarSource(
        client,
        raw_repository,
        dataset_key=_DATASET,
    )
    return source.fetch_candidate(_EXCHANGE, _START, _END), raw_repository


def test_first_write_and_exact_replay_preserve_recorded_knowledge_time() -> None:
    candidate, raw_repository = _candidate()
    repository = DjangoExchangeCalendarSnapshotRepository()

    first = repository.save(candidate)
    replay = repository.save(candidate)

    assert PublicSnapshotModel is ExchangeCalendarSnapshotFactModel
    assert first.snapshot_id == replay.snapshot_id
    assert first.recorded_at == replay.recorded_at
    assert first.content_hash == candidate.content_hash
    assert first.record_digest == replay.record_digest
    assert (
        first.raw_reference.payload_hash
        == raw_repository.get_by_hash(candidate.raw_reference.payload_hash).payload_hash
    )  # type: ignore[union-attr]
    assert ExchangeCalendarSnapshotFactModel._default_manager.count() == 1


def test_exact_read_requires_both_first_seen_and_recorded_cutoffs() -> None:
    candidate, _raw_repository = _candidate()
    repository = DjangoExchangeCalendarSnapshotRepository()
    stored = repository.save(candidate)

    before_first_seen = repository.get_exact(
        stored.reference(),
        known_at=stored.first_seen_at - timedelta(microseconds=1),
    )
    before_recorded = repository.get_exact(
        stored.reference(),
        known_at=stored.first_seen_at,
    )
    exact = repository.get_exact(stored.reference(), known_at=stored.recorded_at)

    assert before_first_seen is None
    assert before_recorded is None
    assert exact == stored


def test_same_raw_response_with_different_normalized_rows_is_rejected() -> None:
    candidate, _raw_repository = _candidate()
    repository = DjangoExchangeCalendarSnapshotRepository()
    stored = repository.save(candidate)
    modified_days = list(candidate.days)
    modified_days[-1] = type(modified_days[-1])(
        exchange=modified_days[-1].exchange,
        calendar_date=modified_days[-1].calendar_date,
        is_open=True,
        previous_open_date=modified_days[-1].previous_open_date,
    )
    conflicting_candidate = type(candidate)(
        exchange=candidate.exchange,
        coverage_start=candidate.coverage_start,
        coverage_end=candidate.coverage_end,
        days=tuple(modified_days),
        provider_name=candidate.provider_name,
        raw_reference=candidate.raw_reference,
        first_seen_at=candidate.first_seen_at,
        source_published_at=candidate.source_published_at,
    )

    with pytest.raises(DataFetchError) as caught:
        repository.save(conflicting_candidate)

    assert getattr(caught.value, "code", None) == "EXCHANGE_CALENDAR_SOURCE_CONTENT_MISMATCH"
    assert ExchangeCalendarSnapshotFactModel._default_manager.count() == 1
    assert repository.get_exact(stored.reference(), known_at=stored.recorded_at) == stored


def test_fact_is_append_only_and_protects_its_raw_source_row() -> None:
    candidate, raw_repository = _candidate()
    repository = DjangoExchangeCalendarSnapshotRepository()
    stored = repository.save(candidate)
    model = ExchangeCalendarSnapshotFactModel._default_manager.get(pk=stored.snapshot_id)
    model.provider_name = "other"

    with pytest.raises(ValidationError):
        model.save()
    with pytest.raises(ValidationError):
        model.delete()

    raw_model = RawPayloadModel._default_manager.get(pk=candidate.raw_reference.payload_id)
    with pytest.raises(ProtectedError):
        raw_model.delete()
    assert raw_repository.get_by_hash(candidate.raw_reference.payload_hash) is not None


def test_corrupt_raw_payload_or_fact_record_is_never_returned_as_a_match() -> None:
    candidate, _raw_repository = _candidate()
    repository = DjangoExchangeCalendarSnapshotRepository()
    stored = repository.save(candidate)
    raw_model = RawPayloadModel._default_manager.get(pk=candidate.raw_reference.payload_id)
    raw_model.payload = {"changed": True}
    raw_model.save()

    with pytest.raises(DataFetchError) as caught:
        repository.get_exact(stored.reference(), known_at=stored.recorded_at)

    assert getattr(caught.value, "code", None) == "EXCHANGE_CALENDAR_RAW_REFERENCE_MISMATCH"
