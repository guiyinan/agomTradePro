"""Capture and verify exact Tushare stock-basic source occurrences."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

from apps.data_center.application.instrument_reference_source import (
    InstrumentReferenceAuditOccurrence,
    InstrumentReferenceAuditOccurrenceReceipt,
    InstrumentReferenceAuditOccurrenceWriterPort,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.domain.entities import (
    RawAudit,
    RawAuditReference,
    raw_audit_content_hash,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceOccurrence,
    InstrumentReferenceProviderContract,
    InstrumentReferenceRecord,
    InstrumentReferenceSourceContractError,
)
from apps.data_center.domain.protocols import RawAuditRepositoryProtocol
from apps.data_center.domain.provider_response import (
    canonical_provider_response_json,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure.tushare_client import TushareResponseEvidence
from core.exceptions import DataFetchError

_AUDIT_LINK_KEY = "instrument_reference_occurrence"
_AUDIT_LINK_SCHEMA = "instrument-reference-raw-audit-occurrence.v1"
_AUDIT_PARSER_VERSION = "instrument-reference-raw-audit.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class _DefaultRawAuditRepositoryPort(RawAuditRepositoryProtocol, Protocol):
    """Require the existing RawAudit repository's explicit default alias."""

    @property
    def unit_of_work_key(self) -> str:
        """Expose the fixed alias identity used by the ORM repository."""


class RawInstrumentReferencePayloadReaderPort(Protocol):
    """Read one exact retained RawPayload by its immutable hash."""

    def get_by_hash(self, payload_hash: str) -> RawPayload | None:
        """Return the exact retained payload or no result."""


class TushareStockBasicClientPort(Protocol):
    """Tushare stock_basic endpoint with exact-response evidence attached."""

    def stock_basic(
        self,
        *,
        exchange: str,
        list_status: str,
        fields: str,
    ) -> object:
        """Request one explicit exchange/status scope and return its response."""


class InstrumentReferenceSourceError(DataFetchError):
    """Raised when a source response cannot form an exact audit-bound candidate."""

    default_message = "证券名录来源响应无法建立精确审计绑定。"
    default_code = "INSTRUMENT_REFERENCE_SOURCE_UNAVAILABLE"


class InstrumentReferenceRawAuditError(DataFetchError):
    """Raised when RawAudit persistence or exact readback is incomplete."""

    default_message = "证券名录来源 RawAudit occurrence 无法验证。"
    default_code = "INSTRUMENT_REFERENCE_RAW_AUDIT_UNAVAILABLE"


class DjangoInstrumentReferenceRawAuditOccurrenceWriter:
    """Write one exact RawAudit occurrence through the default-alias repository."""

    def __init__(self, repository: _DefaultRawAuditRepositoryPort) -> None:
        """Inject the existing repository and reject any non-default database alias."""

        if repository.unit_of_work_key != "django:default":
            raise ValueError("instrument reference RawAudit repository must use default")
        self._repository = repository

    def record(
        self,
        occurrence: InstrumentReferenceAuditOccurrence,
    ) -> InstrumentReferenceAuditOccurrenceReceipt:
        """Append and immediately read back the exact audit row for this response."""

        self._validate_occurrence(occurrence)
        request_params = _validated_redacted_request_params(occurrence)
        request_params_hash = _mapping_sha256(request_params)
        extra = {
            _AUDIT_LINK_KEY: {
                "schema": _AUDIT_LINK_SCHEMA,
                "occurrence_id": str(occurrence.occurrence_id),
                "contract_id": occurrence.contract_id,
                "contract_version": occurrence.contract_version,
                "contract_hash": occurrence.contract_hash,
                "api_name": occurrence.api_name,
                "dataset_key": occurrence.dataset_key,
                "exchange": occurrence.exchange,
                "list_status": occurrence.list_status,
                "fields": occurrence.fields,
                "row_count": occurrence.row_count,
                "database_alias": "default",
                "raw_payload_reference": occurrence.response_reference.to_payload(),
            }
        }
        expected = RawAudit(
            provider_name=occurrence.response_reference.provider_name,
            capability="instrument_reference",
            request_params=request_params,
            status="ok",
            row_count=occurrence.row_count,
            fetched_at=occurrence.response_reference.response_completed_at,
            extra=extra,
            request_params_hash=request_params_hash,
            response_payload_hash=occurrence.response_reference.body_sha256,
            schema_fingerprint=occurrence.raw_payload.schema_fingerprint,
            redacted=True,
            parser_version=_AUDIT_PARSER_VERSION,
            payload_size_bytes=occurrence.response_reference.body_size_bytes,
            run_id=str(occurrence.run_id),
            ingested_run_id=str(occurrence.ingested_run_id),
        )
        try:
            persisted = self._repository.log(expected)
            if not isinstance(persisted, RawAudit):
                raise ValueError("raw audit write returned an invalid row")
            reference = persisted.exact_reference()
            read_back = self._repository.get_by_id(reference.raw_audit_id)
        except Exception as exc:
            raise InstrumentReferenceRawAuditError() from exc
        if not isinstance(read_back, RawAudit) or not self._matches_exact_audit(
            read_back,
            expected=expected,
            expected_reference=reference,
        ):
            raise InstrumentReferenceRawAuditError()
        return InstrumentReferenceAuditOccurrenceReceipt(
            occurrence_id=occurrence.occurrence_id,
            raw_audit_reference=reference,
            raw_payload_id=occurrence.response_reference.payload_id,
            raw_payload_hash=occurrence.response_reference.payload_hash,
            response_body_sha256=occurrence.response_reference.body_sha256,
            request_params_hash=request_params_hash,
            repository_alias="default",
        )

    @staticmethod
    def _validate_occurrence(occurrence: InstrumentReferenceAuditOccurrence) -> None:
        """Validate caller-owned IDs and all provider/body/payload identities."""

        if (
            not isinstance(occurrence, InstrumentReferenceAuditOccurrence)
            or not isinstance(occurrence.occurrence_id, UUID)
            or not isinstance(occurrence.run_id, UUID)
            or not isinstance(occurrence.ingested_run_id, UUID)
            or not isinstance(occurrence.response_reference, ProviderResponsePayloadReference)
            or not isinstance(occurrence.raw_payload, RawPayload)
            or type(occurrence.row_count) is not int
            or occurrence.row_count < 0
            or not isinstance(occurrence.contract_hash, str)
            or not _SHA256.fullmatch(occurrence.contract_hash)
        ):
            raise InstrumentReferenceRawAuditError()
        reference = occurrence.response_reference
        raw_payload = occurrence.raw_payload
        if (
            reference.provider_name != "tushare"
            or reference.dataset_key != occurrence.dataset_key
            or raw_payload.provider_name != reference.provider_name
            or raw_payload.dataset_key != reference.dataset_key
            or raw_payload.payload_id != reference.payload_id
            or raw_payload.payload_hash != reference.payload_hash
            or raw_payload.fetched_at != reference.response_completed_at
            or raw_payload.redacted is not True
            or reference.original_body_retained is not True
            or not reference.verifies(raw_payload)
            or reference.body_sha256 != occurrence.raw_payload.payload.get("response_body_sha256")
            or occurrence.api_name != "stock_basic"
            or not occurrence.fields
            or not occurrence.exchange
            or not occurrence.list_status
        ):
            raise InstrumentReferenceRawAuditError()
        if str(occurrence.run_id) == "" or str(occurrence.ingested_run_id) == "":
            raise InstrumentReferenceRawAuditError()

    @staticmethod
    def _matches_exact_audit(
        persisted: RawAudit,
        *,
        expected: RawAudit,
        expected_reference: RawAuditReference,
    ) -> bool:
        """Require every persisted audit field and its independent content hash."""

        if (
            persisted.raw_audit_id != expected_reference.raw_audit_id
            or persisted.content_hash != expected_reference.content_hash
            or persisted.run_id != expected.run_id
            or persisted.ingested_run_id != expected.ingested_run_id
            or raw_audit_content_hash(persisted) != persisted.content_hash
        ):
            return False
        return _without_audit_identity(persisted) == expected


class TushareInstrumentReferenceSource:
    """Build a blocked source-reference candidate from explicit stock-basic scopes."""

    def __init__(
        self,
        client: TushareStockBasicClientPort,
        raw_payload_reader: RawInstrumentReferencePayloadReaderPort,
        raw_audit_writer: InstrumentReferenceAuditOccurrenceWriterPort,
        *,
        provider_contract: InstrumentReferenceProviderContract,
        exchange_suffix_crosswalk: InstrumentReferenceExchangeSuffixCrosswalk,
    ) -> None:
        """Compose exact-response capture, RawAudit occurrence and identity policy."""

        if not isinstance(provider_contract, InstrumentReferenceProviderContract):
            raise ValueError("provider_contract must be an explicit typed contract")
        if not isinstance(exchange_suffix_crosswalk, InstrumentReferenceExchangeSuffixCrosswalk):
            raise ValueError("exchange_suffix_crosswalk must be explicit")
        if any(
            exchange_suffix_crosswalk.suffix_for(exchange) is None
            for exchange in provider_contract.exchange_scope
        ):
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_CROSSWALK_INVALID")
        self._client = client
        self._raw_payload_reader = raw_payload_reader
        self._raw_audit_writer = raw_audit_writer
        self._provider_contract = provider_contract
        self._exchange_suffix_crosswalk = exchange_suffix_crosswalk

    def fetch_candidate(
        self,
        *,
        run_id: UUID,
        ingested_run_id: UUID,
    ) -> InstrumentReferenceCandidate:
        """Fetch every explicit exchange/status pair and bind rows to exact audits."""

        if not isinstance(run_id, UUID) or not isinstance(ingested_run_id, UUID):
            raise InstrumentReferenceSourceError(
                "caller-owned run identifiers must be UUID values",
                code="INSTRUMENT_REFERENCE_RUN_ID_INVALID",
            )
        occurrences: list[InstrumentReferenceOccurrence] = []
        records: list[InstrumentReferenceRecord] = []
        for exchange in self._provider_contract.exchange_scope:
            for list_status in self._provider_contract.list_status_scope:
                response = self._client.stock_basic(
                    exchange=exchange,
                    list_status=list_status,
                    fields=self._provider_contract.fields_csv,
                )
                provider_reference, raw_payload = self._read_exact_response(response)
                parsed_rows = _parse_stock_basic_rows(
                    raw_payload,
                    provider_reference,
                    provider_contract=self._provider_contract,
                    crosswalk=self._exchange_suffix_crosswalk,
                    exchange=exchange,
                    list_status=list_status,
                )
                occurrence_id = uuid4()
                try:
                    receipt = self._raw_audit_writer.record(
                        InstrumentReferenceAuditOccurrence(
                            occurrence_id=occurrence_id,
                            run_id=run_id,
                            ingested_run_id=ingested_run_id,
                            contract_id=self._provider_contract.contract_id,
                            contract_version=self._provider_contract.contract_version,
                            contract_hash=self._provider_contract.content_hash,
                            api_name=self._provider_contract.api_name,
                            dataset_key=self._provider_contract.dataset_key,
                            exchange=exchange,
                            list_status=list_status,
                            fields=self._provider_contract.fields_csv,
                            row_count=len(parsed_rows),
                            response_reference=provider_reference,
                            raw_payload=raw_payload,
                        )
                    )
                except Exception as exc:
                    raise InstrumentReferenceRawAuditError() from exc
                if not self._valid_receipt(
                    receipt,
                    occurrence_id=occurrence_id,
                    reference=provider_reference,
                    raw_payload=raw_payload,
                    run_id=run_id,
                    ingested_run_id=ingested_run_id,
                ):
                    raise InstrumentReferenceRawAuditError()
                occurrence = InstrumentReferenceOccurrence(
                    occurrence_id=occurrence_id,
                    exchange=exchange,
                    list_status=list_status,
                    raw_audit_reference=receipt.raw_audit_reference,
                    raw_payload_id=provider_reference.payload_id,
                    raw_payload_hash=provider_reference.payload_hash,
                    response_body_sha256=provider_reference.body_sha256,
                    response_completed_at=provider_reference.response_completed_at,
                    row_count=len(parsed_rows),
                )
                occurrences.append(occurrence)
                records.extend(
                    _bind_rows_to_occurrence(
                        parsed_rows,
                        occurrence=occurrence,
                        crosswalk=self._exchange_suffix_crosswalk,
                    )
                )
        try:
            return InstrumentReferenceCandidate(
                provider_contract=self._provider_contract,
                crosswalk=self._exchange_suffix_crosswalk,
                occurrences=tuple(occurrences),
                records=tuple(records),
            )
        except InstrumentReferenceSourceContractError as exc:
            raise InstrumentReferenceSourceError(str(exc), code=exc.code) from exc

    def _read_exact_response(
        self,
        response: object,
    ) -> tuple[ProviderResponsePayloadReference, RawPayload]:
        """Require same-call Tushare evidence and its exact immutable RawPayload."""

        evidence = getattr(response, "response_evidence", None)
        if not isinstance(evidence, TushareResponseEvidence):
            raise InstrumentReferenceSourceError(
                "stock_basic did not return exact response evidence",
                code="INSTRUMENT_REFERENCE_RAW_EVIDENCE_UNAVAILABLE",
            )
        reference = evidence.raw_payload_reference
        if not isinstance(reference, ProviderResponsePayloadReference):
            raise InstrumentReferenceSourceError(
                "stock_basic response has no retained RawPayload reference",
                code="INSTRUMENT_REFERENCE_RAW_EVIDENCE_UNAVAILABLE",
            )
        if (
            reference.provider_name != self._provider_contract.provider_name
            or reference.dataset_key != self._provider_contract.dataset_key
            or reference.body_sha256 != evidence.body_sha256
            or reference.response_completed_at != evidence.response_completed_at
            or reference.original_body_retained is not True
        ):
            raise InstrumentReferenceSourceError(
                "stock_basic response reference does not match the captured call",
                code="INSTRUMENT_REFERENCE_RAW_REFERENCE_MISMATCH",
            )
        try:
            payload = self._raw_payload_reader.get_by_hash(reference.payload_hash)
        except Exception as exc:
            raise InstrumentReferenceSourceError(
                "RawPayload lookup failed",
                code="INSTRUMENT_REFERENCE_RAW_EVIDENCE_UNAVAILABLE",
            ) from exc
        if payload is None or not reference.verifies(payload):
            raise InstrumentReferenceSourceError(
                "RawPayload does not match its exact response reference",
                code="INSTRUMENT_REFERENCE_RAW_REFERENCE_MISMATCH",
            )
        return reference, payload

    @staticmethod
    def _valid_receipt(
        receipt: InstrumentReferenceAuditOccurrenceReceipt,
        *,
        occurrence_id: UUID,
        reference: ProviderResponsePayloadReference,
        raw_payload: RawPayload,
        run_id: UUID,
        ingested_run_id: UUID,
    ) -> bool:
        """Check that the injected writer returned the same verified occurrence."""

        return (
            isinstance(receipt, InstrumentReferenceAuditOccurrenceReceipt)
            and receipt.occurrence_id == occurrence_id
            and receipt.repository_alias == "default"
            and receipt.raw_payload_id == reference.payload_id == raw_payload.payload_id
            and receipt.raw_payload_hash == reference.payload_hash == raw_payload.payload_hash
            and receipt.response_body_sha256 == reference.body_sha256
            and receipt.raw_audit_reference.run_id == str(run_id)
            and receipt.raw_audit_reference.ingested_run_id == str(ingested_run_id)
        )


def _parse_stock_basic_rows(
    raw_payload: RawPayload,
    reference: ProviderResponsePayloadReference,
    *,
    provider_contract: InstrumentReferenceProviderContract,
    crosswalk: InstrumentReferenceExchangeSuffixCrosswalk,
    exchange: str,
    list_status: str,
) -> list[dict[str, object]]:
    """Parse exact retained response bytes and enforce request/schema identity."""

    envelope = _strict_object(raw_payload.payload, "raw payload")
    if (
        envelope.get("api_name") != provider_contract.api_name
        or envelope.get("dataset_key") != provider_contract.dataset_key
        or envelope.get("provider_name") != provider_contract.provider_name
        or envelope.get("original_body_retained") is not True
        or envelope.get("retained_content_encoding") != "exact_original_utf8_json"
        or envelope.get("response_body_sha256") != reference.body_sha256
        or envelope.get("retained_content_sha256") != reference.body_sha256
    ):
        raise InstrumentReferenceSourceError(
            "retained body is not exact stock_basic evidence",
            code="INSTRUMENT_REFERENCE_RAW_REFERENCE_MISMATCH",
        )
    retained_text = envelope.get("retained_response_json")
    if not isinstance(retained_text, str):
        raise InstrumentReferenceSourceError(
            "retained stock_basic body is unavailable",
            code="INSTRUMENT_REFERENCE_RAW_EVIDENCE_UNAVAILABLE",
        )
    if hashlib.sha256(retained_text.encode("utf-8")).hexdigest() != reference.body_sha256:
        raise InstrumentReferenceSourceError(
            "retained stock_basic body digest changed",
            code="INSTRUMENT_REFERENCE_RAW_REFERENCE_MISMATCH",
        )
    _verify_request_scope(
        raw_payload.request_params,
        api_name=provider_contract.api_name,
        fields=provider_contract.fields_csv,
        exchange=exchange,
        list_status=list_status,
    )
    try:
        provider_response = parse_provider_response_json(retained_text.encode("utf-8"))
    except ValueError as exc:
        raise InstrumentReferenceSourceError(
            "retained stock_basic body is not strict JSON",
            code="INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
        ) from exc
    response = _strict_object(provider_response, "provider response")
    if type(response.get("code")) is not int or response.get("code") != 0:
        raise InstrumentReferenceSourceError(
            "stock_basic provider response was not successful",
            code="INSTRUMENT_REFERENCE_PROVIDER_REJECTED",
        )
    data = _strict_object(response.get("data"), "provider data")
    if set(data) - {"fields", "items", "has_more"} or data.get("has_more", False) is not False:
        raise InstrumentReferenceSourceError(
            "stock_basic response is incomplete or has unknown table fields",
            code="INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
        )
    fields = data.get("fields")
    if type(fields) is not list or fields != list(provider_contract.fields):
        raise InstrumentReferenceSourceError(
            "stock_basic returned fields differ from its request contract",
            code="INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
        )
    items = data.get("items")
    if type(items) is not list:
        raise InstrumentReferenceSourceError(
            "stock_basic rows are not a list",
            code="INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
        )
    rows: list[dict[str, object]] = []
    for item in items:
        if type(item) is not list or len(item) != len(provider_contract.fields):
            raise InstrumentReferenceSourceError(
                "stock_basic row does not match the requested schema",
                code="INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
            )
        row = dict(zip(provider_contract.fields, item, strict=True))
        _validate_stock_basic_row(
            row,
            expected_exchange=exchange,
            expected_list_status=list_status,
            crosswalk=crosswalk,
        )
        rows.append(row)
    return rows


def _validate_stock_basic_row(
    row: dict[str, object],
    *,
    expected_exchange: str,
    expected_list_status: str,
    crosswalk: InstrumentReferenceExchangeSuffixCrosswalk,
) -> None:
    """Reject incomplete row values, request drift and unverified code suffixes."""

    for field in ("ts_code", "name", "exchange", "list_status"):
        if not isinstance(row.get(field), str):
            raise InstrumentReferenceSourceError(
                f"stock_basic {field} must be an exact string",
                code="INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
            )
    ts_code = cast(str, row["ts_code"])
    row_exchange = cast(str, row["exchange"])
    row_status = cast(str, row["list_status"])
    if row_exchange != expected_exchange or row_status != expected_list_status:
        raise InstrumentReferenceSourceError(
            "stock_basic row differs from its requested exchange/status",
            code="INSTRUMENT_REFERENCE_REQUEST_SCOPE_MISMATCH",
        )
    if not crosswalk.matches(ts_code, row_exchange):
        raise InstrumentReferenceSourceError(
            "stock_basic ts_code suffix does not match the explicit crosswalk",
            code="INSTRUMENT_REFERENCE_IDENTITY_MISMATCH",
        )
    _optional_exact_text(row.get("market"), "market")
    if "curr_type" in row:
        currency = row["curr_type"]
        if currency is not None and type(currency) is not str:
            raise InstrumentReferenceSourceError(
                "stock_basic curr_type must be an exact string or null",
                code="INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
            )
    _parse_optional_provider_date(row.get("list_date"), "list_date")
    _parse_optional_provider_date(row.get("delist_date"), "delist_date")


def _bind_rows_to_occurrence(
    rows: list[dict[str, object]],
    *,
    occurrence: InstrumentReferenceOccurrence,
    crosswalk: InstrumentReferenceExchangeSuffixCrosswalk,
) -> list[InstrumentReferenceRecord]:
    """Attach verified raw occurrence identity while preserving provider values."""

    result: list[InstrumentReferenceRecord] = []
    for row in rows:
        exchange = cast(str, row["exchange"])
        list_status = cast(str, row["list_status"])
        list_date_raw = cast(str | None, row["list_date"])
        delist_date_raw = cast(str | None, row["delist_date"])
        source_currency = cast(str | None, row["curr_type"]) if "curr_type" in row else None
        try:
            result.append(
                InstrumentReferenceRecord(
                    ts_code=cast(str, row["ts_code"]),
                    name=cast(str, row["name"]),
                    source_exchange=exchange,
                    source_market=cast(str | None, row["market"]),
                    source_list_status=list_status,
                    list_date_raw=list_date_raw,
                    list_date=_parse_optional_provider_date(list_date_raw, "list_date"),
                    delist_date_raw=delist_date_raw,
                    delist_date=_parse_optional_provider_date(delist_date_raw, "delist_date"),
                    source_currency=source_currency,
                    exchange_suffix=cast(str, crosswalk.suffix_for(exchange)),
                    occurrence_id=occurrence.occurrence_id,
                    raw_audit_reference=occurrence.raw_audit_reference,
                    raw_payload_id=occurrence.raw_payload_id,
                    raw_payload_hash=occurrence.raw_payload_hash,
                )
            )
        except InstrumentReferenceSourceContractError as exc:
            raise InstrumentReferenceSourceError(str(exc), code=exc.code) from exc
    return result


def _parse_optional_provider_date(value: object, field: str) -> date | None:
    """Parse exact YYYYMMDD dates, preserving null and empty provider values."""

    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise InstrumentReferenceSourceError(
            f"stock_basic {field} must be null, empty, or exact YYYYMMDD",
            code="INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
        )
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise InstrumentReferenceSourceError(
            f"stock_basic {field} is not a calendar date",
            code="INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
        ) from exc


def _optional_exact_text(value: object, field: str) -> None:
    """Allow only null or raw strings for optional provider fields."""

    if value is not None and not isinstance(value, str):
        raise InstrumentReferenceSourceError(
            f"stock_basic {field} must be a raw string or null",
            code="INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
        )


def _verify_request_scope(
    value: object,
    *,
    api_name: str,
    fields: str,
    exchange: str,
    list_status: str,
) -> None:
    """Require one of the exact request shapes emitted by supported Tushare modes."""

    request = _strict_object(value, "retained request params")
    params = {"exchange": exchange, "list_status": list_status}
    api_request = {"api_name", "fields", "params"}
    sdk_request = {"fields", "params"}
    rest_request = {"exchange", "list_status", "fields"}
    request_api: object
    if set(request) == rest_request:
        actual_params = {
            "exchange": request.get("exchange"),
            "list_status": request.get("list_status"),
        }
        request_api = api_name
    else:
        if set(request) not in (api_request, sdk_request):
            raise InstrumentReferenceSourceError(
                "retained stock_basic request has unsupported filters",
                code="INSTRUMENT_REFERENCE_REQUEST_SCOPE_MISMATCH",
            )
        request_api = request.get("api_name", api_name)
        actual_params = _strict_object(request.get("params"), "request params")
    if request_api != api_name or request.get("fields") != fields or actual_params != params:
        raise InstrumentReferenceSourceError(
            "retained stock_basic request does not match the explicit query",
            code="INSTRUMENT_REFERENCE_REQUEST_SCOPE_MISMATCH",
        )


def _validated_redacted_request_params(
    occurrence: InstrumentReferenceAuditOccurrence,
) -> dict[str, object]:
    """Use only the redacted RawPayload request and bind its exact query scope."""

    _verify_request_scope(
        occurrence.raw_payload.request_params,
        api_name=occurrence.api_name,
        fields=occurrence.fields,
        exchange=occurrence.exchange,
        list_status=occurrence.list_status,
    )
    try:
        parsed = parse_provider_response_json(
            canonical_provider_response_json(occurrence.raw_payload.request_params).encode("utf-8")
        )
    except ValueError as exc:
        raise InstrumentReferenceRawAuditError() from exc
    return _strict_object(parsed, "redacted request params")


def _strict_object(value: object, field: str) -> dict[str, object]:
    """Narrow one JSON object without coercion or unknown key rewriting."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise InstrumentReferenceSourceError(
            f"{field} must be a strict JSON object",
            code="INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
        )
    return cast(dict[str, object], value)


def _mapping_sha256(value: Mapping[str, object]) -> str:
    """Hash an exact request mapping using the retained-response JSON rules."""

    try:
        encoded = canonical_provider_response_json(value).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InstrumentReferenceRawAuditError() from exc
    return hashlib.sha256(encoded).hexdigest()


def _without_audit_identity(audit: RawAudit) -> RawAudit:
    """Remove repository-generated identity so the written content can be compared."""

    return RawAudit(
        provider_name=audit.provider_name,
        capability=audit.capability,
        request_params=audit.request_params,
        status=audit.status,
        row_count=audit.row_count,
        latency_ms=audit.latency_ms,
        error_message=audit.error_message,
        fetched_at=audit.fetched_at,
        extra=audit.extra,
        request_params_hash=audit.request_params_hash,
        response_payload_hash=audit.response_payload_hash,
        schema_fingerprint=audit.schema_fingerprint,
        redacted=audit.redacted,
        parser_version=audit.parser_version,
        payload_size_bytes=audit.payload_size_bytes,
        retention_until=audit.retention_until,
        run_id=audit.run_id,
        ingested_run_id=audit.ingested_run_id,
    )


__all__ = [
    "DjangoInstrumentReferenceRawAuditOccurrenceWriter",
    "InstrumentReferenceRawAuditError",
    "InstrumentReferenceSourceError",
    "RawInstrumentReferencePayloadReaderPort",
    "TushareInstrumentReferenceSource",
    "TushareStockBasicClientPort",
]
