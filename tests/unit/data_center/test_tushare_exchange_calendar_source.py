"""Tushare calendar source requires full, unfiltered, byte-bound responses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256

import pytest

from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarError,
    exchange_calendar_request_scope_hash,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure.tushare_client import TushareResponseEvidence
from apps.data_center.infrastructure.tushare_exchange_calendar_source import (
    TushareExchangeCalendarSource,
)
from core.exceptions import DataFetchError

_FIELDS = "exchange,cal_date,is_open,pretrade_date"
_DATASET = "tushare.exchange_calendar.raw"
_COMPLETED_AT = datetime(2026, 10, 16, 4, 0, 1, tzinfo=UTC)
_ROWS: list[list[object]] = [
    ["SSE", "20261015", 1, "20261014"],
    ["SSE", "20261016", 1, "20261015"],
    ["SSE", "20261017", 0, "20261016"],
    ["SSE", "20261018", 0, "20261016"],
]


class InMemoryRawPayloadRepository:
    """Keep one immutable test payload for source-bound candidate construction."""

    def __init__(self) -> None:
        self.payload: RawPayload | None = None

    def save(self, payload: RawPayload) -> RawPayload:
        self.payload = payload
        return payload

    def get_by_hash(self, payload_hash: str) -> RawPayload | None:
        if self.payload is None or self.payload.payload_hash != payload_hash:
            return None
        return self.payload


@dataclass(frozen=True)
class CapturedCalendarResponse:
    """Mimic the witnessed frame returned only by Tushare's capture path."""

    response_evidence: TushareResponseEvidence


class CapturedCalendarClient:
    """Return exact response metadata and record the endpoint arguments."""

    def __init__(self, evidence: TushareResponseEvidence) -> None:
        self.evidence = evidence
        self.calls: list[dict[str, object]] = []

    def trade_cal(self, **kwargs: object) -> CapturedCalendarResponse:
        self.calls.append(kwargs)
        return CapturedCalendarResponse(self.evidence)


def _response_body(rows: list[list[object]]) -> bytes:
    payload: dict[str, object] = {
        "code": 0,
        "msg": None,
        "data": {"fields": _FIELDS.split(","), "items": rows},
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _source(
    rows: list[list[object]],
    *,
    request_params: dict[str, object] | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> tuple[TushareExchangeCalendarSource, CapturedCalendarClient, InMemoryRawPayloadRepository]:
    body = _response_body(rows)
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=_COMPLETED_AT,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    scope = request_params or {
        "api_name": "trade_cal",
        "fields": _FIELDS,
        "params": {
            "exchange": "SSE",
            "start_date": "20261015",
            "end_date": "20261018",
        },
    }
    raw_repository = InMemoryRawPayloadRepository()
    reference = RetainProviderResponsePayloadUseCase(raw_repository).execute(
        capture,
        provider_name="tushare",
        dataset_key=_DATASET,
        api_name="trade_cal",
        request_params=scope,
        sensitive_values=sensitive_values,
    )
    client = CapturedCalendarClient(
        TushareResponseEvidence(
            body_sha256=reference.body_sha256,
            response_completed_at=reference.response_completed_at,
            raw_payload_reference=reference,
        )
    )
    return (
        TushareExchangeCalendarSource(client, raw_repository, dataset_key=_DATASET),
        client,
        raw_repository,
    )


def test_tushare_source_uses_explicit_exchange_and_unfiltered_complete_window() -> None:
    source, client, raw_repository = _source(_ROWS)

    candidate = source.fetch_candidate("SSE", date(2026, 10, 15), date(2026, 10, 18))

    assert client.calls == [
        {
            "exchange": "SSE",
            "start_date": "20261015",
            "end_date": "20261018",
            "fields": _FIELDS,
        }
    ]
    assert "is_open" not in client.calls[0]
    assert candidate.exchange == "SSE"
    assert tuple(item.is_open for item in candidate.days) == (True, True, False, False)
    assert candidate.raw_reference.payload_id == raw_repository.payload.payload_id  # type: ignore[union-attr]
    assert candidate.first_seen_at == _COMPLETED_AT
    assert candidate.source_published_at is None


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        (
            [["SZSE", "20261015", 1, "20261014"], *_ROWS[1:]],
            "EXCHANGE_CALENDAR_EXCHANGE_MISMATCH",
        ),
        (_ROWS[:-1], "EXCHANGE_CALENDAR_COVERAGE_INCOMPLETE"),
        (
            [*_ROWS[:2], ["SSE", "20261017", 1, "20261015"], _ROWS[3]],
            "EXCHANGE_CALENDAR_PREVIOUS_OPEN_MISMATCH",
        ),
        (
            [*_ROWS[:2], ["SSE", "20261017", True, "20261016"], _ROWS[3]],
            "EXCHANGE_CALENDAR_RESPONSE_SCHEMA_INVALID",
        ),
        (
            [*_ROWS[:2], ["SSE", "20261017", 0.0, "20261016"], _ROWS[3]],
            "EXCHANGE_CALENDAR_RESPONSE_SCHEMA_INVALID",
        ),
    ],
)
def test_tushare_source_rejects_ambiguous_or_incomplete_day_rows(
    rows: list[list[object]],
    code: str,
) -> None:
    source, _client, _repository = _source(rows)

    with pytest.raises((DataFetchError, ExchangeCalendarError)) as caught:
        source.fetch_candidate("SSE", date(2026, 10, 15), date(2026, 10, 18))

    assert caught.value.code == code


def test_tushare_source_rejects_filtered_raw_request_even_if_rows_look_complete() -> None:
    filtered_request: dict[str, object] = {
        "api_name": "trade_cal",
        "fields": _FIELDS,
        "params": {
            "exchange": "SSE",
            "start_date": "20261015",
            "end_date": "20261018",
            "is_open": "1",
        },
    }
    source, client, _repository = _source(_ROWS, request_params=filtered_request)

    with pytest.raises(DataFetchError) as caught:
        source.fetch_candidate("SSE", date(2026, 10, 15), date(2026, 10, 18))

    assert client.calls[0].get("is_open") is None
    assert caught.value.code == "EXCHANGE_CALENDAR_REQUEST_SCOPE_MISMATCH"


def test_tushare_source_rejects_redacted_or_missing_response_bytes() -> None:
    source, client, _repository = _source(
        _ROWS,
        sensitive_values=("calendar-secret-token",),
    )
    body = _response_body(_ROWS).replace(b'"msg":null', b'"msg":"calendar-secret-token"')
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=_COMPLETED_AT,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    repository = InMemoryRawPayloadRepository()
    reference = RetainProviderResponsePayloadUseCase(repository).execute(
        capture,
        provider_name="tushare",
        dataset_key=_DATASET,
        api_name="trade_cal",
        request_params={
            "api_name": "trade_cal",
            "fields": _FIELDS,
            "params": {
                "exchange": "SSE",
                "start_date": "20261015",
                "end_date": "20261018",
            },
        },
        sensitive_values=("calendar-secret-token",),
    )
    client.evidence = TushareResponseEvidence(
        body_sha256=reference.body_sha256,
        response_completed_at=reference.response_completed_at,
        raw_payload_reference=reference,
    )
    redacted_source = TushareExchangeCalendarSource(client, repository, dataset_key=_DATASET)

    with pytest.raises(DataFetchError) as caught:
        redacted_source.fetch_candidate("SSE", date(2026, 10, 15), date(2026, 10, 18))
    assert caught.value.code == "EXCHANGE_CALENDAR_RAW_REFERENCE_MISMATCH"

    no_evidence = CapturedCalendarClient(TushareResponseEvidence("0" * 64, _COMPLETED_AT))
    missing_source = TushareExchangeCalendarSource(
        no_evidence,
        InMemoryRawPayloadRepository(),
        dataset_key=_DATASET,
    )
    with pytest.raises(DataFetchError) as caught:
        missing_source.fetch_candidate("SSE", date(2026, 10, 15), date(2026, 10, 18))
    assert caught.value.code == "EXCHANGE_CALENDAR_RAW_EVIDENCE_UNAVAILABLE"


def test_source_scope_hash_covers_exchange_and_full_date_bounds() -> None:
    assert exchange_calendar_request_scope_hash(
        "SSE", date(2026, 10, 15), date(2026, 10, 18)
    ) != exchange_calendar_request_scope_hash("SZSE", date(2026, 10, 15), date(2026, 10, 18))
