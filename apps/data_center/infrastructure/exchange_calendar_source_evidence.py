"""Strict binding from one retained Tushare body to calendar day facts."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import cast

from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarDay,
    ExchangeCalendarRawReference,
    ExchangeCalendarSnapshotCandidate,
    exchange_calendar_request_scope_hash,
)
from apps.data_center.domain.provider_response import parse_provider_response_json
from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest
from core.exceptions import DataFetchError

_FIELDS = "exchange,cal_date,is_open,pretrade_date"
_DATE_RE = re.compile(r"^[0-9]{8}$")


def candidate_from_retained_calendar_response(
    raw_payload: RawPayload,
    raw_reference: ExchangeCalendarRawReference,
    *,
    exchange: str,
    coverage_start: date,
    coverage_end: date,
) -> ExchangeCalendarSnapshotCandidate:
    """Verify exact raw evidence and normalize complete day facts to date order."""

    if (
        raw_payload.payload_id != raw_reference.payload_id
        or raw_payload.payload_hash != raw_reference.payload_hash
        or raw_payload_record_digest(raw_payload) != raw_reference.record_digest
        or raw_payload.provider_name != raw_reference.provider_name
        or raw_payload.dataset_key != raw_reference.dataset_key
        or raw_payload.fetched_at != raw_reference.response_completed_at
    ):
        raise DataFetchError(
            "Calendar raw payload identity or immutable digest does not match",
            code="EXCHANGE_CALENDAR_RAW_REFERENCE_MISMATCH",
        )
    envelope = _object(raw_payload.payload, "raw_payload")
    if (
        envelope.get("api_name") != "trade_cal"
        or envelope.get("provider_name") != raw_reference.provider_name
        or envelope.get("dataset_key") != raw_reference.dataset_key
        or envelope.get("original_body_retained") is not True
        or envelope.get("retained_content_encoding") != "exact_original_utf8_json"
        or envelope.get("response_body_sha256") != raw_reference.body_sha256
        or envelope.get("retained_content_sha256") != raw_reference.retained_content_sha256
        or envelope.get("transport") != raw_reference.transport
    ):
        raise DataFetchError(
            "Calendar raw payload envelope is not exact original source evidence",
            code="EXCHANGE_CALENDAR_RAW_REFERENCE_MISMATCH",
        )
    completed_text = envelope.get("response_completed_at")
    try:
        envelope_completed_at = datetime.fromisoformat(_text(completed_text, "response time"))
    except ValueError as exc:
        raise DataFetchError(
            "Calendar response completion timestamp is invalid",
            code="EXCHANGE_CALENDAR_RAW_REFERENCE_MISMATCH",
        ) from exc
    if envelope_completed_at != raw_reference.response_completed_at:
        raise DataFetchError(
            "Calendar response completion timestamp differs from its reference",
            code="EXCHANGE_CALENDAR_RAW_REFERENCE_MISMATCH",
        )
    if _exact_int(envelope.get("status_code"), "response status") not in range(200, 300):
        raise DataFetchError(
            "Calendar response was not a successful provider response",
            code="EXCHANGE_CALENDAR_RAW_REFERENCE_MISMATCH",
        )
    body_size = _exact_int(envelope.get("response_body_size_bytes"), "body size")
    retained_json = _text(envelope.get("retained_response_json"), "retained response")
    try:
        body = retained_json.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DataFetchError(
            "Calendar retained response is not valid UTF-8",
            code="EXCHANGE_CALENDAR_RESPONSE_INVALID",
        ) from exc
    body_digest = hashlib.sha256(body).hexdigest()
    retained_digest = _text(envelope.get("retained_content_sha256"), "content digest")
    if (
        len(body) != body_size
        or body_digest != raw_reference.body_sha256
        or body_digest != retained_digest
    ):
        raise DataFetchError(
            "Calendar retained bytes do not match their exact source digests",
            code="EXCHANGE_CALENDAR_RAW_REFERENCE_MISMATCH",
        )
    _verify_request_scope(
        raw_payload.request_params,
        raw_reference,
        exchange=exchange,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )
    try:
        provider_payload = parse_provider_response_json(body)
    except ValueError as exc:
        raise DataFetchError(
            "Calendar provider body is not strict JSON",
            code="EXCHANGE_CALENDAR_RESPONSE_INVALID",
        ) from exc
    response = _object(provider_payload, "provider response")
    provider_code = response.get("code")
    if type(provider_code) is not int or provider_code != 0:
        raise DataFetchError(
            "Calendar provider returned a non-success response",
            code="EXCHANGE_CALENDAR_PROVIDER_REJECTED",
        )
    data = _object(response.get("data"), "provider data")
    fields = data.get("fields")
    if type(fields) is not list or fields != _FIELDS.split(","):
        raise DataFetchError(
            "Calendar provider response fields do not match the requested schema",
            code="EXCHANGE_CALENDAR_RESPONSE_SCHEMA_INVALID",
        )
    items = data.get("items")
    if type(items) is not list:
        raise DataFetchError(
            "Calendar provider response items are invalid",
            code="EXCHANGE_CALENDAR_RESPONSE_SCHEMA_INVALID",
        )
    days: list[ExchangeCalendarDay] = []
    for row in items:
        if type(row) is not list or len(row) != 4:
            raise DataFetchError(
                "Calendar provider row does not match the requested schema",
                code="EXCHANGE_CALENDAR_RESPONSE_SCHEMA_INVALID",
            )
        row_exchange = _text(row[0], "row exchange")
        if row_exchange != exchange:
            raise DataFetchError(
                "Calendar provider row exchange differs from request",
                code="EXCHANGE_CALENDAR_EXCHANGE_MISMATCH",
            )
        calendar_date = _parse_provider_date(row[1], "calendar date")
        is_open = _parse_open_state(row[2])
        previous_open_date = _parse_provider_date(row[3], "previous open date")
        days.append(
            ExchangeCalendarDay(
                exchange=row_exchange,
                calendar_date=calendar_date,
                is_open=is_open,
                previous_open_date=previous_open_date,
            )
        )
    return ExchangeCalendarSnapshotCandidate(
        exchange=exchange,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        days=tuple(sorted(days, key=lambda day: day.calendar_date)),
        provider_name=raw_reference.provider_name,
        raw_reference=raw_reference,
        first_seen_at=raw_reference.response_completed_at,
        source_published_at=None,
    )


def _verify_request_scope(
    request_params: object,
    raw_reference: ExchangeCalendarRawReference,
    *,
    exchange: str,
    coverage_start: date,
    coverage_end: date,
) -> None:
    """Require exact calendar request fields and no open-only filter."""

    request = _object(request_params, "request params")
    if set(request) not in ({"fields", "params"}, {"api_name", "fields", "params"}):
        raise DataFetchError(
            "Calendar request parameters contain an unsupported filter or scope",
            code="EXCHANGE_CALENDAR_REQUEST_SCOPE_MISMATCH",
        )
    if request.get("api_name", "trade_cal") != "trade_cal":
        raise DataFetchError(
            "Calendar request API name is invalid",
            code="EXCHANGE_CALENDAR_REQUEST_SCOPE_MISMATCH",
        )
    if request.get("fields") != _FIELDS:
        raise DataFetchError(
            "Calendar request fields are incomplete",
            code="EXCHANGE_CALENDAR_REQUEST_SCOPE_MISMATCH",
        )
    params = _object(request.get("params"), "request scope")
    expected_params = {
        "exchange": exchange,
        "start_date": coverage_start.strftime("%Y%m%d"),
        "end_date": coverage_end.strftime("%Y%m%d"),
    }
    if params != expected_params:
        raise DataFetchError(
            "Calendar request scope differs from the requested complete window",
            code="EXCHANGE_CALENDAR_REQUEST_SCOPE_MISMATCH",
        )
    expected_hash = exchange_calendar_request_scope_hash(
        exchange,
        coverage_start,
        coverage_end,
    )
    if raw_reference.request_scope_sha256 != expected_hash:
        raise DataFetchError(
            "Calendar request digest differs from the requested complete window",
            code="EXCHANGE_CALENDAR_REQUEST_SCOPE_MISMATCH",
        )


def _parse_provider_date(value: object, field_name: str) -> date:
    """Parse only canonical eight-digit Tushare calendar dates."""

    text = _text(value, field_name)
    if not _DATE_RE.fullmatch(text):
        raise DataFetchError(
            f"Tushare {field_name} is invalid",
            code="EXCHANGE_CALENDAR_RESPONSE_SCHEMA_INVALID",
        )
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise DataFetchError(
            f"Tushare {field_name} is invalid",
            code="EXCHANGE_CALENDAR_RESPONSE_SCHEMA_INVALID",
        ) from exc


def _parse_open_state(value: object) -> bool:
    """Accept only documented exact integer/string 0 or 1 scalars."""

    if type(value) is int and value in {0, 1}:
        return value == 1
    if type(value) is str and value in {"0", "1"}:
        return value == "1"
    raise DataFetchError(
        "Tushare is_open must be exact 0 or 1",
        code="EXCHANGE_CALENDAR_RESPONSE_SCHEMA_INVALID",
    )


def _object(value: object, field_name: str) -> dict[str, object]:
    """Narrow one JSON object at the provider boundary."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise DataFetchError(
            f"{field_name} must be a JSON object",
            code="EXCHANGE_CALENDAR_RESPONSE_SCHEMA_INVALID",
        )
    return cast(dict[str, object], value)


def _text(value: object, field_name: str) -> str:
    """Narrow one non-empty provider string without coercion."""

    if type(value) is not str or not value:
        raise DataFetchError(
            f"{field_name} must be a non-empty string",
            code="EXCHANGE_CALENDAR_RESPONSE_SCHEMA_INVALID",
        )
    return value


def _exact_int(value: object, field_name: str) -> int:
    """Narrow one real integer without accepting bool or float equality."""

    if type(value) is not int:
        raise DataFetchError(
            f"{field_name} must be an integer",
            code="EXCHANGE_CALENDAR_RESPONSE_SCHEMA_INVALID",
        )
    return value


__all__ = ["candidate_from_retained_calendar_response"]
