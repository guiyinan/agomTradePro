"""Explicit, raw-body-captured Tushare adapter for exchange calendars."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from apps.data_center.application.exchange_calendar import ExchangeCalendarSnapshotSourcePort
from apps.data_center.application.provider_response_payload import ProviderResponsePayloadReference
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarError,
    ExchangeCalendarRawReference,
    ExchangeCalendarSnapshotCandidate,
    exchange_calendar_request_scope_hash,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure.exchange_calendar_source_evidence import (
    candidate_from_retained_calendar_response,
)
from apps.data_center.infrastructure.tushare_client import TushareResponseEvidence
from core.exceptions import DataFetchError

_FIELDS = "exchange,cal_date,is_open,pretrade_date"


class TushareCalendarClientPort(Protocol):
    """Tushare calendar endpoint surface with captured response evidence."""

    def trade_cal(
        self,
        *,
        exchange: str,
        start_date: str,
        end_date: str,
        fields: str,
    ) -> object:
        """Fetch the unfiltered full-date calendar endpoint."""


class RawCalendarPayloadReaderPort(Protocol):
    """Read the exact immutable RawPayload named by a capture reference."""

    def get_by_hash(self, payload_hash: str) -> RawPayload | None:
        """Return a retained provider response by its immutable hash."""


class TushareExchangeCalendarSource(ExchangeCalendarSnapshotSourcePort):
    """Fetch complete daily status using explicit exchange and raw-response opt-in."""

    def __init__(
        self,
        client: TushareCalendarClientPort,
        raw_payload_reader: RawCalendarPayloadReaderPort,
        *,
        dataset_key: str,
    ) -> None:
        if not dataset_key or dataset_key.strip() != dataset_key:
            raise ValueError("dataset_key must be explicit canonical text")
        self._client = client
        self._raw_payload_reader = raw_payload_reader
        self._dataset_key = dataset_key

    def fetch_candidate(
        self,
        exchange: str,
        coverage_start: date,
        coverage_end: date,
    ) -> ExchangeCalendarSnapshotCandidate:
        """Fetch every date, require exact retained bytes, then parse the body itself."""

        request_scope_hash = exchange_calendar_request_scope_hash(
            exchange,
            coverage_start,
            coverage_end,
        )
        response = self._client.trade_cal(
            exchange=exchange,
            start_date=coverage_start.strftime("%Y%m%d"),
            end_date=coverage_end.strftime("%Y%m%d"),
            fields=_FIELDS,
        )
        evidence = getattr(response, "response_evidence", None)
        if not isinstance(evidence, TushareResponseEvidence):
            raise DataFetchError(
                "Tushare calendar response did not include exact transport evidence",
                code="EXCHANGE_CALENDAR_RAW_EVIDENCE_UNAVAILABLE",
            )
        provider_reference = evidence.raw_payload_reference
        if not isinstance(provider_reference, ProviderResponsePayloadReference):
            raise DataFetchError(
                "Tushare calendar response was not retained as RawPayload",
                code="EXCHANGE_CALENDAR_RAW_EVIDENCE_UNAVAILABLE",
            )
        if (
            provider_reference.dataset_key != self._dataset_key
            or provider_reference.provider_name != "tushare"
            or provider_reference.body_sha256 != evidence.body_sha256
            or provider_reference.response_completed_at != evidence.response_completed_at
            or provider_reference.original_body_retained is not True
            or provider_reference.retained_content_encoding != "exact_original_utf8_json"
        ):
            raise DataFetchError(
                "Tushare calendar raw reference does not match the configured request",
                code="EXCHANGE_CALENDAR_RAW_REFERENCE_MISMATCH",
            )
        raw_payload = self._raw_payload_reader.get_by_hash(provider_reference.payload_hash)
        if raw_payload is None:
            raise DataFetchError(
                "Tushare calendar RawPayload is unavailable",
                code="EXCHANGE_CALENDAR_RAW_REFERENCE_MISSING",
            )
        try:
            raw_reference = ExchangeCalendarRawReference(
                payload_id=provider_reference.payload_id,
                payload_hash=provider_reference.payload_hash,
                record_digest=provider_reference.record_digest,
                body_sha256=provider_reference.body_sha256,
                retained_content_sha256=provider_reference.retained_content_sha256,
                request_scope_sha256=request_scope_hash,
                original_body_retained=provider_reference.original_body_retained,
                response_completed_at=provider_reference.response_completed_at,
                provider_name=provider_reference.provider_name,
                dataset_key=provider_reference.dataset_key,
                transport=provider_reference.transport.value,
            )
        except ExchangeCalendarError as exc:
            raise DataFetchError(str(exc), code=exc.code) from exc
        return candidate_from_retained_calendar_response(
            raw_payload,
            raw_reference,
            exchange=exchange,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
        )


__all__ = [
    "RawCalendarPayloadReaderPort",
    "TushareCalendarClientPort",
    "TushareExchangeCalendarSource",
]
